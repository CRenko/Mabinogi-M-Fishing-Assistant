"""制作页面交互回归；所有引擎操作均为 Mock，不连接游戏。"""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox, QLabel
from PySide6.QtGui import QPalette

from fishing_assistant.config import AppConfig
from fishing_assistant.crafting import CraftOptions
from fishing_assistant.crafting_ui import CraftingPage
from fishing_assistant.features.crafting.model import CraftProgress
from fishing_assistant.desktop.styles import DAY_STYLE, NIGHT_STYLE
from fishing_assistant.window_target import WindowInfo


class CraftingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = Mock()
        self.engine.config.return_value = AppConfig(crafting_recipe="silk", crafting_mode="exhaust", crafting_count=7)
        self.engine.is_monitoring.return_value = False
        self.engine.is_crafting.return_value = False
        self.engine.start_crafting.return_value = True
        window = WindowInfo(123, "瑪奇 Mobile", 0, 0, 1920, 1080)
        with patch("fishing_assistant.features.crafting.page.window_target.list_target_windows", return_value=[window]):
            self.page = CraftingPage(self.engine)

    def tearDown(self):
        self.page.timer.stop()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_restore_plan_does_not_overwrite_saved_selection(self):
        self.assertEqual(self.page.category.currentData(), "cloth")
        self.assertEqual(self.page.recipe.currentData(), "silk")
        self.assertEqual(self.page.count.value(), 7)
        self.assertTrue(self.page.count.isHidden())
        self.engine.update_config.assert_not_called()

    def test_cancel_is_default_and_never_starts(self):
        def cancel(dialog):
            self.assertEqual(dialog.defaultButton().text(), "取消")
            self.assertIn("丝绸", dialog.text())
            dialog.defaultButton().click()
        with patch.object(QMessageBox, "exec", cancel):
            self.page.start_task()
        self.engine.start_crafting.assert_not_called()

    def test_confirmation_is_readable_and_safe_in_both_themes(self):
        def luminance(color):
            linear = [value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4
                      for value in color.getRgbF()[:3]]
            return sum(value*weight for value, weight in zip(linear, (.2126, .7152, .0722)))

        def inspect(dialog):
            self.assertTrue(dialog.testOption(QMessageBox.Option.DontUseNativeDialog))
            dialog.show()
            self.app.processEvents()
            self.assertIn("消耗", dialog.informativeText())
            self.assertIn("丝绸", dialog.text())
            confirm = next(button for button in dialog.buttons() if button.text() == "开始制作")
            self.assertNotEqual(confirm.palette().color(QPalette.ColorRole.Button),
                                dialog.defaultButton().palette().color(QPalette.ColorRole.Button))
            for name in ("qt_msgbox_label", "qt_msgbox_informativelabel"):
                label = dialog.findChild(QLabel, name)
                self.assertIsNotNone(label)
                self.assertTrue(label.isVisible())
                fg = luminance(label.palette().color(QPalette.ColorRole.WindowText))
                bg = luminance(dialog.palette().color(QPalette.ColorRole.Window))
                self.assertGreaterEqual((max(fg, bg)+.05)/(min(fg, bg)+.05), 4.5)
            self.assertLess(dialog.width(), 640)
            dialog.defaultButton().click()
            dialog.close()

        for style in (DAY_STYLE, NIGHT_STYLE, DAY_STYLE):
            self.page.setStyleSheet(style)
            with patch.object(QMessageBox, "exec", inspect):
                self.page.start_task()
        self.engine.start_crafting.assert_not_called()

    def test_explicit_confirmation_starts_only_selected_recipe(self):
        def accept(dialog):
            next(button for button in dialog.buttons() if button.text() == "开始制作").click()
        with patch.object(QMessageBox, "exec", accept):
            self.page.start_task()
        self.engine.start_crafting.assert_called_once_with(CraftOptions("silk", "exhaust", 7), 123)

    def test_failed_start_keeps_previous_counts_and_reports_failure(self):
        self.page.update_progress(CraftProgress("done", "上次已完成", 7, 7, ("empty",)*5, 0, False))
        self.engine.start_crafting.return_value = False
        def accept(dialog):
            next(button for button in dialog.buttons() if button.text() == "开始制作").click()
        with patch.object(QMessageBox, "exec", accept):
            self.page.start_task()
        self.assertIn("未启动", self.page.state.text())
        self.assertIn("未启动", self.page.log.toPlainText())
        self.assertIn("7 次", self.page.totals.text())
        self.assertEqual(len(self.page.slot_labels), 5)
        self.assertNotIn("正在识别", self.page.capacity_status.text())

    def test_missing_target_never_opens_confirmation(self):
        self.page.target.setCurrentIndex(-1)
        with patch.object(QMessageBox, "exec") as dialog:
            self.page.start_task()
        dialog.assert_not_called()
        self.engine.start_crafting.assert_not_called()
        self.assertIn("窗口", self.page.detail.text())

    def test_confirmation_cannot_be_reentered(self):
        calls = []
        def cancel(dialog):
            calls.append(dialog)
            if len(calls) == 1:
                self.page.start_task()
            dialog.defaultButton().click()
        with patch.object(QMessageBox, "exec", cancel):
            self.page.start_task()
        self.assertEqual(len(calls), 1)
        self.engine.start_crafting.assert_not_called()
        self.assertTrue(self.page.start.isEnabled())

    def test_target_selection_updates_start_without_waiting_for_timer(self):
        self.page.target.setCurrentIndex(-1)
        self.assertFalse(self.page.start.isEnabled())
        self.page.target.setCurrentIndex(0)
        self.assertTrue(self.page.start.isEnabled())

    def test_confirmation_uses_the_original_target_window(self):
        self.page.target.addItem("另一个游戏窗口", 777)
        def accept(dialog):
            self.page.target.setCurrentIndex(1)
            next(button for button in dialog.buttons() if button.text() == "开始制作").click()
        with patch.object(QMessageBox, "exec", accept):
            self.page.start_task()
        self.engine.start_crafting.assert_called_once_with(CraftOptions("silk", "exhaust", 7), 123)

    def test_busy_task_disables_selection_and_start(self):
        self.engine.is_monitoring.return_value = True
        self.page.sync_running()
        for widget in (self.page.category, self.page.recipe, self.page.mode, self.page.count, self.page.start):
            self.assertFalse(widget.isEnabled())
        self.assertFalse(self.page.stop.isEnabled())
        self.engine.is_crafting.return_value = True
        self.page.sync_running()
        self.assertTrue(self.page.stop.isEnabled())

    def test_queue_capacity_defaults_to_auto_and_layout_is_dynamic(self):
        self.assertEqual(self.page.capacity.value(), 0)
        self.page._resize_slot_labels(1)
        self.assertEqual(len(self.page.slot_labels), 1)
        self.assertEqual(self.page.slots_layout.getItemPosition(0)[:2], (0, 0))

        self.page._resize_slot_labels(5)
        self.assertEqual(len(self.page.slot_labels), 5)
        positions = [self.page.slots_layout.getItemPosition(i)[:2]
                     for i in range(5)]
        self.assertEqual(positions, [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)])

        self.page.update_progress(CraftProgress(
            "inspect", "已识别 5 格队列", 0, 0,
            ("empty", "busy", "complete", "unknown", "empty"),
            0, True,
        ))
        self.assertIn("当前队列 5 格", self.page.capacity_status.text())
        self.assertIn("1 格待确认", self.page.capacity_status.text())


if __name__ == "__main__":
    unittest.main()
