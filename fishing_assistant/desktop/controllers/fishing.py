"""钓鱼模式、恢复策略和背包清理的配置交互"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QDialog
from fishing_assistant.desktop.dialogs import (
    InventoryCleanupTestDialog,
    InventoryCleanupWarningDialog,
    WOnlyModeWarningDialog,
)
from fishing_assistant.engine import FishingEngine


class FishingSettingsControllerMixin:
    """钓鱼模式、恢复策略和背包清理的配置交互；由 MainWindow 组装，不单独实例化。"""

    def _catch_strategy_changed(self) -> None:
        self.engine.update_config(catch_strategy=str(self.catch_strategy_combo.currentData()))
        self._sync_catch_strategy_controls()

    def _recovery_mode_changed(self) -> None:
        mode = str(self.recovery_mode_combo.currentData())
        if mode == "w_only":
            dialog = WOnlyModeWarningDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                blocker = QSignalBlocker(self.recovery_mode_combo)
                ws_index = self.recovery_mode_combo.findData("ws")
                self.recovery_mode_combo.setCurrentIndex(max(0, ws_index))
                del blocker
                self.engine.update_config(recovery_movement_mode="ws")
                self._sync_recovery_mode_controls()
                return
        self.engine.update_config(recovery_movement_mode=mode)
        self._sync_recovery_mode_controls()

    def _sync_recovery_mode_controls(self) -> None:
        mode = str(self.recovery_mode_combo.currentData())
        self.recovery_mode_stack.setCurrentIndex(1 if mode == "w_only" else 0)
        self.auto_recover_check.setText(
            "自动恢复钓鱼图标"
        )
        self.auto_recover_check.setToolTip(
            "检测到指南针时仅按 W 向前恢复。" if mode == "w_only"
            else "检测到指南针时执行 W → S 往返恢复。"
        )

    def _inventory_cleanup_toggled(self, checked: bool) -> None:
        if checked:
            dialog = InventoryCleanupWarningDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                blocker = QSignalBlocker(self.inventory_cleanup_check)
                self.inventory_cleanup_check.setChecked(False)
                del blocker
                self.engine.update_config(
                    inventory_auto_cleanup_enabled=False
                )
                self._sync_inventory_cleanup_debug_controls()
                return
        self.engine.update_config(inventory_auto_cleanup_enabled=checked)
        self._sync_inventory_cleanup_debug_controls()

    def _sync_inventory_cleanup_debug_controls(self) -> None:
        config = self.engine.config()
        calibrated = (
            config.target_button_offset is not None
            if config.capture_mode == "window"
            else config.button_center is not None
        )
        monitoring = self.engine.is_monitoring()
        self.test_inventory_cleanup_button.setEnabled(
            calibrated and not monitoring
        )
        if not calibrated:
            message = "请先完成 F7 校准。"
        elif monitoring:
            message = "请先停止当前任务。"
        else:
            message = "已就绪 · 无需开启正式自动清理"
        self.inventory_cleanup_test_status.setText(message)
        self.inventory_cleanup_test_status.setToolTip("测试会真实整理物品，但不会修改正式功能开关；开始前仍需确认风险。")

    def _test_inventory_cleanup(self) -> None:
        if self.engine.is_monitoring():
            self.inventory_cleanup_test_status.setText(
                "请先暂停普通监测，再开始测试。"
            )
            return
        dialog = InventoryCleanupTestDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.inventory_cleanup_test_status.setText(
                "已取消，未执行任何游戏操作。"
            )
            return
        if self.engine.request_inventory_cleanup_test():
            self.inventory_cleanup_test_status.setText(
                "清理测试正在运行，请查看控制台状态和日志。"
            )
        self._sync_inventory_cleanup_debug_controls()

    def _fallback_delay_changed(self, value: float) -> None:
        self.engine.update_config(
            fallback_collect_delay_seconds=float(value)
        )
        if self.catch_strategy_combo.currentData() == "fixed_delay":
            self._sync_catch_strategy_controls()

    def _latest_collect_changed(self, value: float) -> None:
        self.engine.update_config(
            fixed_delay_latest_collect_seconds=float(value)
        )
        if self.catch_strategy_combo.currentData() == "fixed_delay":
            self._sync_catch_strategy_controls()

    def _sync_catch_strategy_controls(self) -> None:
        strategy = str(self.catch_strategy_combo.currentData())
        stack_index = {"stamina_bounce": 0, "fixed_delay": 1, "instant": 2}.get(strategy, 0)
        self.catch_option_stack.setCurrentIndex(stack_index)
        delay = float(self.fallback_delay_spin.value())
        latest = float(self.latest_collect_spin.value())
        effective = min(delay, latest)
        self.fixed_delay_effective_hint.setText(
            f"等待时间超过上限，将在 {effective:.1f} 秒收杆。"
        )
        self.fixed_delay_effective_hint.setVisible(delay > latest)
        hints = {
            "stamina_bounce": "体力条回绿时收杆；识别失效时使用学习计时。",
            "fixed_delay": "按设定时间收杆，目标提前消失则跳过。",
            "instant": "上钩立即收杆，也可能收起垃圾。",
        }
        self.catch_strategy_hint.setText(hints.get(strategy, hints["stamina_bounce"]))
        self._sync_learned_escape_status()

    def _sync_learned_escape_status(self) -> None:
        learned = self.engine.config().learned_escape_seconds
        if learned <= 0:
            self.learned_escape_label.setText(
                "尚无计时记录"
            )
            return
        target, _margin = FishingEngine.learned_collect_timing(learned)
        self.learned_escape_label.setText(
            f"上次跑鱼 {learned:.1f} 秒 · 兜底收杆 {target:.1f} 秒"
        )
