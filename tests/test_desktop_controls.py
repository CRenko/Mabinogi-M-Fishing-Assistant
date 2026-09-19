"""食物预留入口、悬浮栏操作及主题勾选标记的离线测试。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPalette
from PySide6.QtCore import Qt
from fishing_assistant.constants import resource_path
from fishing_assistant.desktop.floating_status import FloatingStatusBar
from fishing_assistant.desktop.pages.crafting import CraftingHubPage
from fishing_assistant.desktop.styles import DAY_STYLE, NIGHT_STYLE


class DesktopControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_food_is_separate_placeholder_without_start_button(self):
        from PySide6.QtWidgets import QPushButton
        material = QWidget()
        hub = CraftingHubPage(material)
        try:
            self.assertEqual(hub.count(),2)
            self.assertIs(hub.widget(0), material)
            self.assertIn("食物制作",hub.tabText(1))
            texts = " ".join(w.text() for w in hub.widget(1).findChildren(QLabel))
            self.assertIn("本版本暂未开放",texts)
            self.assertFalse(hub.widget(1).findChildren(QPushButton))
        finally:
            hub.close()

    def test_floating_buttons_equal_width_no_focus_and_correct_enabled_state(self):
        bar = FloatingStatusBar()
        pause,resume = Mock(),Mock()
        bar.pause_requested.connect(pause)
        bar.resume_requested.connect(resume)
        try:
            for theme in ("day","night"):
                bar.set_theme(theme)
                bar.show()
                self.app.processEvents()
                self.assertLessEqual(abs(bar.pause_button.width()-bar.resume_button.width()),1)
                self.assertEqual(bar.pause_button.height(),bar.resume_button.height())
                self.assertEqual(bar.pause_button.focusPolicy(),Qt.FocusPolicy.NoFocus)
                self.assertLess(bar.pause_button.width(), bar.runtime_label.width())
                for button in (bar.pause_button, bar.resume_button):
                    self.assertFalse(button.icon().isNull())
                    self.assertEqual(button.cursor().shape(), Qt.CursorShape.PointingHandCursor)
                bar.set_task_controls(True,False)
                self.assertTrue(bar.pause_button.isEnabled())
                self.assertFalse(bar.resume_button.isEnabled())
                self.assertNotEqual(bar.pause_button.palette().color(QPalette.ColorRole.Button),
                                    bar.resume_button.palette().color(QPalette.ColorRole.Button))
                bar.pause_button.click()
                bar.set_task_controls(True,True)
                self.assertFalse(bar.pause_button.isEnabled())
                self.assertTrue(bar.resume_button.isEnabled())
                bar.resume_button.click()
                bar.set_task_controls(False,False)
                self.assertFalse(bar.pause_button.isEnabled() or bar.resume_button.isEnabled())
            self.assertEqual(pause.call_count,2)
            self.assertEqual(resume.call_count,2)
        finally:
            bar.close()

    def test_both_themes_use_valid_font_independent_checkmark(self):
        path = resource_path("fishing_assistant","assets","checkmark.svg")
        self.assertTrue(QSvgRenderer(str(path)).isValid())
        for style in (DAY_STYLE,NIGHT_STYLE):
            self.assertIn(path.as_posix(),style)
            self.assertIn("indicator:checked:disabled",style)
            self.assertIn("QLabel#fieldLabel",style)

    def test_hidden_floating_window_replaces_previous_theme_palette(self):
        bar = FloatingStatusBar()
        try:
            title = bar.findChild(QLabel,"floatingTitle")
            for theme,expected in (("day","#172b45"),("night","#f4f9ff"),("day","#172b45")):
                bar.hide()
                bar.set_theme(theme)
                bar.show()
                self.app.processEvents()
                self.assertEqual(title.palette().color(QPalette.ColorRole.WindowText).name(),expected)
        finally:
            bar.close()


if __name__ == "__main__":
    unittest.main()
