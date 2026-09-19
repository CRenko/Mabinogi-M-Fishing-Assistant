"""F9 现场保存、连续识别失败取证和环境提示"""
from __future__ import annotations

import cv2
import mss
import numpy as np
import threading
from fishing_assistant import window_target
from fishing_assistant.automation.models import EventKind, IconState
from fishing_assistant.config import AppConfig, effective_roi_size
from fishing_assistant.diagnostics import VISION_DIAGNOSTICS_DIR, record_error
from fishing_assistant.vision import diagnostics as vision_diagnostics
from pathlib import Path


class DiagnosticsMixin:
    """F9 现场保存、连续识别失败取证和环境提示；由 FishingEngine 组装，不单独实例化。"""

    def request_debug_capture(self) -> bool:
        with self._config_lock:
            return self._request_debug_capture()

    def _request_debug_capture(self) -> bool:
        """F9 与界面共用异步入口；同一时间只生成一份诊断。"""
        if self.is_paused():
            self._emit(EventKind.DIAGNOSTIC, "任务暂停中；请先停止任务再保存钓鱼诊断，避免干扰待确认操作。", snapshot_state="failed")
            return False
        if self.is_crafting():
            self._emit(EventKind.DIAGNOSTIC, "自动制作期间暂不执行钓鱼 F9 取证；请先停止制作，避免改变后台悬停位置。", snapshot_state="failed")
            return False
        if self._shutdown.is_set() or not self._debug_capture_lock.acquire(blocking=False):
            return False
        config = self.config()
        self._emit(EventKind.DIAGNOSTIC, "正在保存识别现场…", snapshot_state="saving")

        def worker() -> None:
            try:
                self.save_debug_capture(config)
            except Exception as error:
                record_error("F9 diagnostic worker", error)
                if not self._shutdown.is_set():
                    self._emit(EventKind.DIAGNOSTIC, f"保存识别现场失败：{error}", snapshot_state="failed")
            finally:
                self._debug_capture_lock.release()

        try:
            self._debug_capture_thread = threading.Thread(
                target=worker, name="f9-diagnostic", daemon=True
            )
            self._debug_capture_thread.start()
        except Exception as error:
            self._debug_capture_lock.release()
            self._emit(EventKind.DIAGNOSTIC, f"无法启动诊断保存：{error}", snapshot_state="failed")
            return False
        return True

    def save_debug_capture(self, config: AppConfig | None = None) -> Path | None:
        """从同一张画面保存 ROI 和诊断包；不发送游戏按键或改变校准。"""
        config = config or self.config()
        if config.capture_mode == "window":
            missing_calibration = config.target_button_offset is None
        else:
            missing_calibration = config.button_center is None
        if missing_calibration:
            self._emit(
                EventKind.DIAGNOSTIC, "请先按 F7 校准，再按 F9 保存识别现场。",
                snapshot_state="failed",
            )
            return None
        diagnostic_path: Path | None = None
        try:
            frame, center, capture_info = self._diagnostic_capture_context(config, capture_frame=True)
            if frame is None or not frame.size or center is None:
                raise RuntimeError("没有取得有效画面或校准坐标，请检查游戏窗口")
            height, width = frame.shape[:2]
            x, y = center
            coordinate_width, coordinate_height = (
                capture_info["expected_size"] if config.capture_mode == "window" else (width, height)
            )
            if not (0 <= x < coordinate_width and 0 <= y < coordinate_height):
                raise RuntimeError("校准点不在当前画面内，请回到游戏重新按 F7 校准")
            if config.capture_mode == "window":
                expected_width, expected_height = capture_info["expected_size"]
                roi_width, roi_height = effective_roi_size(config, (expected_width, expected_height))
                scale_x, scale_y = width / expected_width, height / expected_height
                x, y = round(x * scale_x), round(y * scale_y)
                center = (x, y)
                roi_width, roi_height = max(1, round(roi_width * scale_x)), max(1, round(roi_height * scale_y))
                if roi_width > width or roi_height > height:
                    raise RuntimeError("窗口画面小于识别区域，请恢复游戏窗口尺寸")
                left = min(max(0, x - roi_width // 2), width - roi_width)
                top = min(max(0, y - roi_height // 2), height - roi_height)
            else:
                roi_width, roi_height = effective_roi_size(config)
                left, top = x - roi_width // 2, y - roi_height // 2
            roi = frame[max(0, top):min(height, top + roi_height),
                        max(0, left):min(width, left + roi_width), :3].copy()
            capture_info["roi_bounds"] = [max(0, left), max(0, top), roi.shape[1], roi.shape[0]]
            capture_info["frame_button_center"] = list(center)
            diagnostic_path = self.export_diagnostic_snapshot(
                "F9 手动快照", frame=frame, config=config,
                local_center=center, capture_info=capture_info, roi=roi, announce=False,
            )
            if diagnostic_path is None:
                raise RuntimeError("诊断包生成失败，详情见本地错误日志")
            image_path = diagnostic_path.with_name(f"{diagnostic_path.stem}-roi.png")
            encoded_ok, encoded = cv2.imencode(".png", roi)
            if not encoded_ok:
                raise RuntimeError("截图编码失败")
            # OpenCV 的 imwrite 在部分 Windows 中文路径下会失败而只返回 False。
            image_path.write_bytes(encoded.tobytes())
        except Exception as error:  # pragma: no cover - 依赖实际显示器状态
            record_error("F9 diagnostic capture", error)
            if self._shutdown.is_set():
                return None
            self._emit(
                EventKind.DIAGNOSTIC,
                (f"诊断包已保存，但单独截图保存失败：{error}；可在 ZIP 内查看 roi.png。"
                 if diagnostic_path else f"保存识别现场失败：{error}"),
                diagnostic_path=diagnostic_path,
                snapshot_state="partial" if diagnostic_path else "failed",
            )
            return None
        if self._shutdown.is_set():
            return image_path
        self._emit(
            EventKind.DIAGNOSTIC,
            f"识别现场已保存：截图 {image_path}；诊断包 {diagnostic_path}。仅保存在本机，不会自动上传。",
            debug_image=image_path, diagnostic_path=diagnostic_path, snapshot_state="saved",
        )
        return image_path

    def _diagnostic_capture_context(
        self,
        config: AppConfig,
        *,
        capture_frame: bool,
    ) -> tuple[np.ndarray | None, tuple[int, int] | None, dict[str, object]]:
        """返回完整捕获帧、帧内校准坐标和可序列化的捕获环境。"""
        capture_info: dict[str, object] = {
            "capture_mode": config.capture_mode,
            "display_mode": config.display_mode,
            "selected_resolution": config.selected_resolution,
            "monitor_index": config.monitor_index,
        }
        if config.capture_mode == "window":
            target = self._resolve_target_window(config)
            capture_info.update(
                target_title=target.title,
                target_handle=target.handle,
                expected_size=[target.width, target.height],
                button_center=list(config.target_button_offset)
                if config.target_button_offset is not None
                else None,
                window_backend=config.window_backend,
            )
            frame = None
            if capture_frame:
                # 诊断只读画面，不调用钓鱼流程的虚拟悬停，以免干扰背包操作。
                if config.window_backend == "ok":
                    with self._backend_lock:
                        if self._shutdown.is_set():
                            raise RuntimeError("程序正在退出，已取消截图")
                        frame = self._get_ok_window_backend(target).capture_frame(target)
                else:
                    frame = window_target.capture_window_frame(target.handle)
                frame = frame[:, :, :3].copy()
            return frame, config.target_button_offset, capture_info

        with mss.MSS() as screen:
            monitor_index = min(
                max(1, int(config.monitor_index)), len(screen.monitors) - 1
            )
            monitor = screen.monitors[monitor_index]
            origin_x, origin_y = int(monitor["left"]), int(monitor["top"])
            expected_size = [int(monitor["width"]), int(monitor["height"])]
            center = None
            if config.button_center is not None:
                center = (
                    int(config.button_center[0]) - origin_x,
                    int(config.button_center[1]) - origin_y,
                )
            capture_info.update(
                monitor_index=monitor_index,
                monitor_origin=[origin_x, origin_y],
                expected_size=expected_size,
                button_center=list(center) if center is not None else None,
            )
            frame = (
                np.asarray(screen.grab(monitor))[:, :, :3].copy()
                if capture_frame
                else None
            )
        return frame, center, capture_info

    def _emit_environment_warnings(
        self, config: AppConfig | None = None
    ) -> None:
        """启动体检只报告有直接证据的风险，失败不会阻碍监测。"""
        config = config or self.config()
        capture_info: dict[str, object] = {
            "capture_mode": config.capture_mode,
            "display_mode": config.display_mode,
            "selected_resolution": config.selected_resolution,
            "monitor_index": config.monitor_index,
        }
        try:
            _frame, _center, capture_info = self._diagnostic_capture_context(
                config, capture_frame=False
            )
        except Exception:
            pass
        try:
            environment = vision_diagnostics.collect_environment(
                capture_info=capture_info
            )
            for message in vision_diagnostics.summarize_environment(environment):
                self._emit(
                    EventKind.WARNING,
                    f"环境体检：{message}",
                    monitoring=True,
                )
        except Exception:
            pass

    def _track_unrecognized(
        self,
        icon_state: "IconState",
        now: float,
        config: AppConfig,
    ) -> None:
        """连续未识别超阈值时自动保存现场，并限制频率和每次监测份数。"""
        if icon_state != IconState.NORMAL:
            self._unrecognized_since = None
            return
        if self._unrecognized_since is None:
            self._unrecognized_since = now
            return
        elapsed = now - self._unrecognized_since
        if elapsed < self._UNRECOGNIZED_SNAPSHOT_AFTER_S:
            return
        if self._diag_snapshot_count >= self._UNRECOGNIZED_SNAPSHOT_MAX:
            return
        if (
            self._last_diag_snapshot_at is not None
            and now - self._last_diag_snapshot_at
            < self._UNRECOGNIZED_SNAPSHOT_COOLDOWN_S
        ):
            return
        self._diag_snapshot_count += 1
        self._last_diag_snapshot_at = now
        self.export_diagnostic_snapshot(
            f"连续 {elapsed:.0f} 秒未识别出任何状态", config=config
        )

    def export_diagnostic_snapshot(
        self,
        reason: str,
        frame: np.ndarray | None = None,
        config: AppConfig | None = None,
        out_dir: Path | None = None,
        *,
        local_center: tuple[int, int] | None = None,
        capture_info: dict[str, object] | None = None,
        roi: np.ndarray | None = None,
        announce: bool = True,
    ) -> Path | None:
        """保存环境、逐层识别结果和完整捕获帧；失败只写警示。"""
        try:
            config = config or self.config()
            if frame is None:
                frame, local_center, capture_info = self._diagnostic_capture_context(
                    config, capture_frame=True
                )
            else:
                frame = frame[:, :, :3].copy()
                if capture_info is None:
                    local_center = (
                        config.target_button_offset
                        if config.capture_mode == "window"
                        else config.button_center
                    )
                    capture_info = {
                        "capture_mode": config.capture_mode,
                        "display_mode": config.display_mode,
                        "selected_resolution": config.selected_resolution,
                        "monitor_index": config.monitor_index,
                        "expected_size": [int(frame.shape[1]), int(frame.shape[0])],
                        "button_center": (
                            list(local_center) if local_center is not None else None
                        ),
                    }
            pipeline = vision_diagnostics.run_pipeline_check(frame, local_center)
            environment = vision_diagnostics.collect_environment(
                frame_shape=tuple(frame.shape) if frame is not None else None,
                capture_info=capture_info,
            )
            summary = {
                "display_mode": config.display_mode,
                "capture_mode": config.capture_mode,
                "selected_resolution": config.selected_resolution,
                "button_center": config.button_center,
                "target_button_offset": config.target_button_offset,
                "recognition_backend": config.recognition_backend,
                "v2_vision_enabled": config.v2_vision_enabled,
                "monitor_index": config.monitor_index,
                "window_backend": config.window_backend,
                "roi_width": config.roi_width,
                "roi_height": config.roi_height,
                "auto_scale_roi": config.auto_scale_roi,
            }
            target = out_dir if out_dir is not None else VISION_DIAGNOSTICS_DIR
            path = vision_diagnostics.write_snapshot(
                target,
                frame,
                reason=reason,
                environment=environment,
                pipeline=pipeline,
                config_summary=summary,
                roi_bgr=roi,
            )
        except Exception as error:
            record_error("export recognition diagnostic", error, extra={"reason": reason})
            if announce:
                self._emit(EventKind.WARNING, f"识别诊断生成失败：{error}")
            return None
        if announce:
            self._emit(
                EventKind.SUCCESS,
                f"识别诊断已保存（{reason}）：{path}。文件只保存在本机。",
            )
        return path
