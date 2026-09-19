"""只模拟截图和输入：背包入口识别与危险开关保护。"""
import unittest
from unittest.mock import patch
import cv2
import numpy as np

from fishing_assistant.config import AppConfig
from fishing_assistant.engine import FishingEngine
from fishing_assistant.inventory_cleanup import InventoryCleanupVision, BoldCleanupState
from test_inventory_cleanup import FIXTURES, _panel_frame, _simple_state
from fishing_assistant.inventory_cleanup import TemplateMatch


class InventoryEntryTests(unittest.TestCase):
    def setUp(self):
        with patch("fishing_assistant.engine.load_config", return_value=AppConfig()):
            self.engine = FishingEngine()
        self.engine._enabled.set()
        self.frame = np.zeros((1080,1920,3), np.uint8)
        self.safe = _simple_state((True, False, False, False))
        self.match = TemplateMatch(1760,790,50,26,.95,1)
        for name, value in (("_capture_stamina_frame", self.frame), ("_press_key", None), ("_click_game_point", None)):
            mocked = patch.object(self.engine, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def open(self):
        return self.engine._open_cleanup_panel(None, AppConfig(), 0)

    def test_already_on_simple_panel_never_toggles_inventory(self):
        with patch.object(self.engine, "_detect_cleanup_entry", return_value=self.safe):
            self.assertIs(self.open(), self.safe)
        self.engine._press_key.assert_not_called()
        self.engine._click_game_point.assert_not_called()

    def test_already_on_inventory_only_clicks_detected_entry(self):
        with patch.object(self.engine, "_detect_cleanup_entry", return_value=self.match), \
             patch.object(self.engine, "_wait_cleanup_screen", return_value=(self.frame,self.safe)):
            self.assertIs(self.open(), self.safe)
        self.engine._press_key.assert_not_called()
        self.engine._click_game_point.assert_called_once_with(self.match.center, AppConfig(), None)

    def test_game_view_opens_i_once_then_accepts_direct_simple_panel(self):
        with patch.object(self.engine, "_detect_cleanup_entry", return_value=None), \
             patch.object(InventoryCleanupVision, "find_inventory_tab", return_value=None), \
             patch.object(self.engine, "_wait_cleanup_screen", return_value=(self.frame,self.safe)):
            self.open()
        self.engine._press_key.assert_called_once_with("i", AppConfig())
        self.engine._click_game_point.assert_not_called()

    def test_visible_inventory_tab_waits_without_closing_backpack(self):
        with patch.object(self.engine, "_detect_cleanup_entry", return_value=None), \
             patch.object(InventoryCleanupVision, "find_inventory_tab", return_value=self.match), \
             patch.object(self.engine, "_wait_cleanup_screen", side_effect=[(self.frame,self.match),(self.frame,self.safe)]):
            self.open()
        self.engine._press_key.assert_not_called()
        self.engine._click_game_point.assert_called_once()

    def test_stopping_during_entry_recognition_sends_no_input(self):
        def detect(_):
            self.engine.set_monitoring(False)
            return self.match
        from fishing_assistant.automation.models import _OperationCancelled
        with patch.object(self.engine, "_detect_cleanup_entry", side_effect=detect):
            with self.assertRaises(_OperationCancelled):
                self.open()
        self.engine._press_key.assert_not_called()
        self.engine._click_game_point.assert_not_called()


class InventorySwitchSafetyTests(unittest.TestCase):
    def test_plain_gray_cannot_impersonate_off_switch(self):
        frame = _panel_frame(FIXTURES / "cleanup_simple_off.png",1920,1080,1)
        state = InventoryCleanupVision.inspect_simple_screen(frame)
        roi = InventoryCleanupVision._scaled_roi(frame,state.anchor,(30,118,105,166))
        roi[:] = (90,90,90)
        self.assertEqual(InventoryCleanupVision.inspect_simple_screen(frame).bold_cleanup, BoldCleanupState.UNKNOWN)

    def test_desaturated_on_switch_is_not_off(self):
        frame = _panel_frame(FIXTURES / "cleanup_simple_on.png",1920,1080,1)
        state = InventoryCleanupVision.inspect_simple_screen(frame)
        roi = InventoryCleanupVision._scaled_roi(frame,state.anchor,(30,118,105,166))
        roi[:] = cv2.cvtColor(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        self.assertNotEqual(InventoryCleanupVision.inspect_simple_screen(frame).bold_cleanup, BoldCleanupState.OFF)

    def test_right_aligned_panel_and_on_switch_scale(self):
        for factor in (1,4/3,2):
            panel = cv2.imread(str(FIXTURES / "cleanup_simple_on.png"))
            panel = cv2.resize(panel,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA)
            frame = np.full((round(1080*factor),round(1920*factor),3),35,np.uint8)
            frame[50:50+panel.shape[0],-panel.shape[1]:] = panel
            state = InventoryCleanupVision.inspect_simple_screen(frame)
            self.assertIsNotNone(state)
            self.assertEqual(state.bold_cleanup,BoldCleanupState.ON)


if __name__ == "__main__":
    unittest.main()
