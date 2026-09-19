import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np

from fishing_assistant.config import AppConfig
from fishing_assistant.crafting import CraftOptions, CraftSession, CraftView
from fishing_assistant.crafting_runtime import run_crafting
from fishing_assistant.engine import FishingEngine
from fishing_assistant.window_geometry import ClientFrame, ClientGeometry


class CraftRuntimeTests(unittest.TestCase):
    def setUp(self):
        with patch("fishing_assistant.engine.load_config", return_value=AppConfig()):
            self.engine = FishingEngine()
        self.target = SimpleNamespace(handle=123, title="test game", width=1920, height=1080)
        self.clock = 0.0
        self.session = CraftSession(CraftOptions(count=1), 0)
        self.request = (self.session, self.target)
        self.engine._craft_request = self.request
        self.engine._enabled.set()
        self.engine._work_context.generation = 0
        self.backend = Mock()
        self.backend.capture_client_frame.return_value = ClientFrame(
            np.zeros((1080,1920,3), np.uint8),
            ClientGeometry(123, "test game", 10, 30, 1920, 1080, 1940, 1120, 1.0))
        self.view = CraftView("wood", ("empty",)*4, (800,400), (170,790))
        self.overview = self.view
        self.sent = []
        self.last_add = 0
        self.inspections = 0

    def wait(self, seconds):
        self.clock += seconds
        if self.clock > 60:
            raise AssertionError("test exceeded virtual deadline")
        return False

    def inspect(self, *_, **_kwargs):
        self.inspections += 1
        if self.view.slots and self.view.slots[0] == "busy" and self.clock-self.last_add > 3:
            self.view = replace(self.view, slots=("complete","empty","empty","empty"))
        return self.view

    def click(self, target, point):
        self.sent.append(("click", point))
        if point == (800,400):
            self.view = replace(self.overview, dialog_open=True, dialog_recipe="wood", process_point=(1500,920))
        elif point == (170,790):
            self.view = CraftView(result=True)
        else:
            self.fail(f"unexpected click {point}")

    def key(self, key):
        self.sent.append(("key", key))
        if self.view.result:
            self.view = self.overview
        else:
            self.view = replace(self.overview, slots=("busy","empty","empty","empty"))
            self.last_add = self.clock

    def run_task(self, inspect=None, get_window=None):
        def click(target, snapshot, point, *, before_input, check_active):
            snapshot.validate()
            check_active()
            before_input()
            self.click(target, point)
        def key(target, snapshot, key, *, before_input, check_active):
            snapshot.validate()
            check_active()
            before_input()
            self.key(key)
        self.backend.click_client.side_effect = click
        self.backend.tap_client_key.side_effect = key
        vision = Mock()
        vision.inspect.side_effect = inspect or self.inspect
        with patch("fishing_assistant.features.crafting.runner.CraftVision", return_value=vision), \
             patch("fishing_assistant.features.crafting.runner.window_target.get_window_info", side_effect=get_window or (lambda _: self.target)), \
             patch.object(self.engine,"_get_ok_window_backend", return_value=self.backend), \
             patch.object(self.engine._shutdown,"wait", side_effect=self.wait), \
             patch("fishing_assistant.features.crafting.runner.time.monotonic", side_effect=lambda:self.clock):
            run_crafting(self.engine, self.request, 0)

    def test_complete_cycle_actions_and_count(self):
        self.run_task()
        self.assertEqual(self.sent, [("click",(800,400)),("key","space"),("click",(170,790)),("key","space")])
        self.assertEqual((self.session.submitted,self.session.collected), (1,1))
        self.assertFalse(self.engine.is_monitoring())
        self.assertIsNone(self.engine._craft_request)

    def test_stop_after_capture_sends_no_input(self):
        def cancelled(*_, **_kwargs):
            self.engine.set_monitoring(False)
            return self.overview
        self.run_task(inspect=cancelled)
        self.assertFalse(self.sent)

    def test_window_frame_size_difference_does_not_block_crafting(self):
        # 重现报告：外框 1940×1040，游戏客户区 1920×1000，并非点击失效。
        self.target.width, self.target.height = 1940, 1040
        self.backend.capture_client_frame.return_value = ClientFrame(
            np.zeros((1000,1920,3), np.uint8),
            ClientGeometry(123, "test game", 10, 30, 1920, 1000, 1940, 1040, 1.25))
        self.run_task()
        self.assertEqual((self.session.submitted, self.session.collected), (1, 1))
        self.assertEqual(len(self.sent), 4)
        self.backend.capture_frame.assert_not_called()
        self.backend.click.assert_not_called()

    def test_stop_during_hover_cannot_send_space(self):
        self.backend.hover_client.side_effect = lambda *a, **kw: self.engine.set_monitoring(False)
        self.run_task()
        self.assertEqual(self.sent, [("click", (800,400))])
        self.backend.tap_client_key.assert_not_called()

    def test_resize_before_click_stops_without_clicking(self):
        changed = SimpleNamespace(handle=123, title="test game", width=1280,height=720)
        self.run_task(get_window=lambda _: changed if self.inspections >= 2 else self.target)
        self.assertFalse(self.sent)
        self.assertEqual(self.session.phase,"error")

    def test_delivery_error_never_repeats_click(self):
        def uncertain(*_):
            self.sent.append(("click","uncertain"))
            raise RuntimeError("delivery unknown")
        self.click = uncertain
        self.run_task()
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.session.phase,"error")

    def test_missing_window_has_bounded_retry(self):
        self.run_task(get_window=lambda _:None)
        self.assertFalse(self.sent)
        self.assertEqual(self.session.phase,"error")
        self.assertFalse(self.engine.is_monitoring())


if __name__ == "__main__":
    unittest.main()
