"""启动诊断、更新检查与日志导出交互"""
from __future__ import annotations

import threading
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication
from fishing_assistant.constants import APP_VERSION, GITHUB_REPOSITORY
from fishing_assistant.desktop.dialogs import UpdateAvailableDialog
from fishing_assistant.diagnostics import (
    LOG_DIR,
    VISION_DIAGNOSTICS_DIR,
    create_support_bundle,
    record_error,
    set_system_profile,
)
from fishing_assistant.engine import EventKind
from fishing_assistant.system_profile import SystemProfile, collect_system_profile
from fishing_assistant.updates import UpdateResult, check_github_release


class ApplicationServicesMixin:
    """启动诊断、更新检查与日志导出交互；由 MainWindow 组装，不单独实例化。"""

    def begin_startup_services(self) -> None:
        """启动页结束后读取一次硬件；按用户设置决定是否检查 Release。"""
        if hasattr(self, "remote_panel"):
            self.remote_panel.reporter.start()
        threading.Thread(
            target=self._collect_system_profile_async,
            name="system-profile",
            daemon=True,
        ).start()
        if self.engine.config().github_auto_check:
            self._check_for_updates(manual=False)

    def _collect_system_profile_async(self) -> None:
        try:
            self.profile_ready.emit(collect_system_profile())
        except Exception as error:  # pragma: no cover - 取决于本机 WMI 状态
            record_error("collect system profile", error)
            self.profile_ready.emit(None)

    def _show_system_profile(self, profile: object) -> None:
        if not isinstance(profile, SystemProfile):
            self.cpu_model_label.setText("读取失败，已写入本地错误日志。")
            self.gpu_model_label.setText("读取失败，已写入本地错误日志。")
            self.memory_model_label.setText("读取失败，已写入本地错误日志。")
            return
        set_system_profile(profile)
        self.cpu_model_label.setText(profile.cpu)
        self.gpu_model_label.setText(profile.gpu)
        self.memory_model_label.setText(profile.memory)
        self._append_log("已读取一次本机硬件信息（不持续监测）。", EventKind.INFO)

    def _save_update_preferences(self) -> None:
        # 仅固定更新源仓库；是否启动检查由用户的复选框决定。
        self.engine.update_config(github_repository=GITHUB_REPOSITORY)

    def _check_for_updates(self, *, manual: bool) -> None:
        self._save_update_preferences()
        repository = GITHUB_REPOSITORY
        self.check_update_button.setEnabled(False)
        self.update_status.setText("正在检查更新…")

        def worker() -> None:
            try:
                result = check_github_release(repository, APP_VERSION)
            except Exception as error:
                result = UpdateResult(False, f"检查更新失败，请稍后重试：{error}")
            if not result.ok:
                record_error(
                    "GitHub update check",
                    result.message,
                    extra={"repository": repository, "manual": manual},
                )
            self.update_ready.emit(result)

        threading.Thread(target=worker, name="github-update-check", daemon=True).start()

    def _show_update_result(self, result: object) -> None:
        self.check_update_button.setEnabled(True)
        if not isinstance(result, UpdateResult):
            self.update_status.setText("更新检查结果无效，详情已写入本地错误日志。")
            return
        self.update_status.setText(result.message)
        self._last_release_url = result.release_url
        self.open_release_button.setEnabled(bool(result.release_url))
        if result.ok:
            self._append_log(result.message, EventKind.INFO)
        if (
            result.update_available
            and result.latest_version
            and result.latest_version != self._notified_release_version
        ):
            self._notified_release_version = result.latest_version
            self._show_update_dialog(result)

    def _show_update_dialog(self, result: UpdateResult) -> None:
        if self._update_dialog is not None:
            self._update_dialog.close()
        dialog = UpdateAvailableDialog(result, self)
        self._update_dialog = dialog
        dialog.finished.connect(
            lambda _code, current=dialog: self._clear_update_dialog(current)
        )
        dialog.open()

    def _clear_update_dialog(self, dialog: UpdateAvailableDialog) -> None:
        if self._update_dialog is dialog:
            self._update_dialog = None

    def _open_release_page(self) -> None:
        if self._last_release_url:
            QDesktopServices.openUrl(QUrl(self._last_release_url))

    def _create_diagnostic_bundle(self) -> None:
        try:
            self.engine.export_diagnostic_snapshot("设置页手动生成")
            bundle_path = create_support_bundle()
        except OSError as error:
            record_error("create diagnostic bundle", error)
            self.diagnostic_status.setText("生成诊断包失败，详情已写入本地错误日志。")
            return
        QApplication.clipboard().setText(str(bundle_path))
        self.diagnostic_status.setText(
            f"已在本机生成诊断包，并将路径复制到剪贴板：{bundle_path}。请自行发送给项目维护者。"
        )
        self._append_log("已生成本地诊断包；不会自动上传。", EventKind.INFO)

    def _view_snapshot(self) -> None:
        path = self._last_snapshot_path
        if path is None or not path.is_file():
            self.snapshot_status.setText("截图不存在或已被移动，请重新按 F9 保存。")
            self.view_snapshot_button.setEnabled(False)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.snapshot_status.setText("无法打开图片查看器，请从诊断目录手动打开截图。")

    def _open_snapshot_directory(self) -> None:
        directory = (
            self._last_snapshot_bundle.parent
            if self._last_snapshot_bundle else VISION_DIAGNOSTICS_DIR
        )
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                raise OSError("系统未能打开目录")
        except OSError as error:
            self.snapshot_status.setText(f"无法打开诊断目录：{error}")

    def _open_log_directory(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))
