"""发现最小化窗口不等于允许后台执行，所有 Windows 调用均拦截。"""
import unittest
from unittest.mock import MagicMock, patch

from fishing_assistant import window_target as windows
from fishing_assistant.window_target import WindowInfo


class WindowDiscoveryTests(unittest.TestCase):
    def test_normalized_game_titles_and_suffix(self):
        for title in ("瑪奇 Mobile", "玛奇 Mobile", "瑪奇\u00a0Mobile", "瑪奇　Ｍｏｂｉｌｅ", "瑪奇 Mobile - 登录中"):
            with self.subTest(title=title):
                target = WindowInfo(12, title, 0, 0, 1280, 800)
                self.assertEqual(windows.find_mabinogi_mobile_window([target]), target)
        browser = WindowInfo(20, "瑪奇 Mobile 攻略 - Edge", 0, 0, 1280, 800)
        self.assertIsNone(windows.find_mabinogi_mobile_window([browser]))

    def test_ambiguous_games_require_selection_and_exact_handle_wins(self):
        first = WindowInfo(12, "瑪奇 Mobile", 0, 0, 1280, 800)
        second = WindowInfo(13, first.title, 0, 0, 1920, 1080)
        self.assertIsNone(windows.find_mabinogi_mobile_window([first, second]))
        self.assertIsNone(windows.select_target_window([first, second], 99, first.title))
        self.assertEqual(windows.select_target_window([first, second], 13, second.title), second)

    def test_reused_handle_does_not_select_unrelated_application(self):
        other = WindowInfo(12, "其他应用", 0, 0, 800, 600)
        new_game = WindowInfo(99, "瑪奇 Mobile", 0, 0, 1280, 800)
        self.assertEqual(windows.select_target_window([other, new_game], 12, new_game.title), new_game)
        self.assertIsNone(windows.select_target_window([other], 12, new_game.title))

    def minimized_api(self):
        api = MagicMock()
        api.IsWindow.return_value = 1
        api.IsWindowVisible.return_value = 1
        api.IsIconic.return_value = 1
        api.GetWindowTextLengthW.return_value = len("瑪奇 Mobile")
        def set_title(_handle, buffer, _length):
            buffer.value = "瑪奇 Mobile"
            return len(buffer.value)
        api.GetWindowTextW.side_effect = set_title
        api.EnumWindows.side_effect = lambda callback, param: callback(12, param)
        return api

    def test_minimized_discovery_uses_restored_bounds_but_execution_rejects(self):
        api = self.minimized_api()
        with patch.object(windows, "_user32", api), patch.object(windows, "_require_windows"), \
             patch("win32gui.GetWindowPlacement", return_value=(0, 2, (0, 0), (0, 0), (100, 200, 2660, 1800))):
            found = windows.list_target_windows(include_minimized=True)
            self.assertEqual(found, [WindowInfo(12, "瑪奇 Mobile", 100, 200, 2560, 1600, True)])
            self.assertIn("已最小化", found[0].display_label)
            self.assertIsNone(windows.get_window_info(12))
            self.assertIsNone(windows.resolve_window(12, "瑪奇 Mobile"))
            self.assertEqual(windows.list_target_windows(), [])
            api.GetWindowRect.assert_not_called()
