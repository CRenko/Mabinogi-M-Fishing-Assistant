"""暂停/继续不能跨代发送按键，也不能重放已添加的制作项目。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from fishing_assistant.config import AppConfig
from fishing_assistant.engine import FishingEngine, EventKind
from fishing_assistant.automation.models import _OperationCancelled
from fishing_assistant.features.crafting.model import CraftOptions, CraftSession, CraftView
from fishing_assistant.features.crafting.runner import _step_and_send, run_crafting
from fishing_assistant.window_geometry import ClientFrame, ClientGeometry


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        with patch("fishing_assistant.engine.load_config", return_value=AppConfig()):
            self.engine = FishingEngine(self.events.append)
        self.engine._enabled.set()
        self.engine._work_context.generation = 0
        self.target = SimpleNamespace(handle=101, title="game", width=1920, height=1080)
        self.session = CraftSession(CraftOptions(count=1), 0)

    def crafting(self):
        self.engine._craft_request = (self.session, self.target)

    def test_pause_keeps_task_reserved_and_invalidates_old_input(self):
        self.assertTrue(self.engine.pause_task())
        self.assertTrue(self.engine.is_monitoring())
        self.assertTrue(self.engine.is_paused())
        self.assertFalse(self.engine._operation_active(0))
        with self.assertRaises(_OperationCancelled):
            self.engine._ensure_operation_active()
        self.assertFalse(self.engine.request_inventory_cleanup_test())
        self.assertFalse(self.engine.request_debug_capture())

    def test_resume_fishing_requires_new_frame_and_does_not_send_keys(self):
        self.engine.pause_task()
        with patch.object(self.engine, "_schedule_recast") as schedule, patch.object(self.engine, "_press_key") as press:
            self.assertTrue(self.engine.resume_task())
        self.assertFalse(self.engine.is_paused())
        self.assertTrue(self.engine._startup_probe_active)
        self.assertFalse(self.engine._operation_active(0))
        self.assertTrue(self.engine._operation_active(self.engine._interrupt_generation))
        schedule.assert_called_once()
        press.assert_not_called()

    def test_stop_cannot_be_resumed_and_repeated_pause_is_idempotent(self):
        self.engine.pause_task()
        generation = self.engine._interrupt_generation
        self.engine.pause_task()
        self.assertEqual(self.engine._interrupt_generation, generation)
        self.engine.set_monitoring(False)
        self.assertFalse(self.engine.is_paused())
        self.assertFalse(self.engine.resume_task())

    def test_cleanup_pause_is_irrevocable_stop(self):
        for flag in (self.engine._cleanup_in_progress, self.engine._cleanup_test_requested):
            self.engine._enabled.set()
            flag.set()
            self.engine.pause_task()
            self.assertFalse(self.engine.is_monitoring())
            self.assertFalse(self.engine.resume_task())
            flag.clear()

    def test_cleanup_cannot_start_from_stale_frame_while_paused(self):
        self.engine.pause_task()
        with patch.object(self.engine,"_open_cleanup_panel") as enter:
            self.engine._perform_inventory_cleanup(AppConfig(),1.0)
        enter.assert_not_called()
        self.assertTrue(self.engine.is_paused())

    def test_crafting_pause_preserves_counters_and_game_deadline(self):
        self.crafting()
        self.session.submitted = 1
        self.session.expected_end = 90
        self.session.phase_since = 3
        with patch("fishing_assistant.automation.pause.time.monotonic", return_value=10):
            self.engine.pause_task()
        with patch("fishing_assistant.automation.pause.time.monotonic", return_value=110):
            self.engine.resume_task()
        self.assertEqual(self.session.submitted, 1)
        self.assertEqual(self.session.expected_end, 90)
        self.assertEqual(self.session.phase_since, 103)

    def test_pause_before_click_rolls_back_unsent_decision(self):
        self.crafting()
        view = CraftView("wood", ("empty",)*4, (800, 400), (170, 790))
        self.session.step(view, 0)
        def window(_):
            self.engine.pause_task()
            return self.target
        backend = Mock()
        with patch("fishing_assistant.features.crafting.runner.window_target.get_window_info", side_effect=window), \
             patch("fishing_assistant.features.crafting.runner.time.monotonic", return_value=1), \
             patch.object(self.engine, "_get_ok_window_backend", return_value=backend):
            with self.assertRaises(_OperationCancelled):
                _step_and_send(self.engine, self.session, view, self.snapshot(), self.target, self.target)
        self.assertEqual(self.session.phase, "inspect")
        backend.click_client.assert_not_called()

    def snapshot(self):
        return ClientFrame(np.zeros((1080,1920,3), np.uint8),
            ClientGeometry(101, "game", 0, 0, 1920, 1080, 1920, 1080, 1.0))

    def test_pause_during_geometry_check_rolls_back_unsent_decision(self):
        self.crafting()
        view = CraftView("wood", ("empty",)*4, (800,400), (170,790))
        self.session.step(view, 0)
        backend = Mock()
        def before_click(*args, before_input, check_active):
            self.engine.pause_task()
            before_input()
            self.fail("paused operation must not reach input")
        backend.click_client.side_effect = before_click
        with patch("fishing_assistant.features.crafting.runner.window_target.get_window_info", return_value=self.target), \
             patch("fishing_assistant.features.crafting.runner.time.monotonic", return_value=1), \
             patch.object(self.engine, "_get_ok_window_backend", return_value=backend):
            with self.assertRaises(_OperationCancelled):
                _step_and_send(self.engine, self.session, view, self.snapshot(), self.target, self.target)
        self.assertEqual(self.session.phase, "inspect")
        self.assertEqual(self.session.submitted, 0)

    def test_sent_add_is_confirmed_once_after_resume(self):
        self.crafting()
        self.session.phase = "await_add"
        self.session.before_add = 0
        self.session.resume_after_pause(100)
        view = CraftView("wood", ("complete", "empty", "empty", "empty"), (800,400), (170,790))
        self.session.step(view, 101)
        decision = self.session.step(view, 102)
        self.assertEqual(self.session.submitted, 1)
        self.assertNotEqual(decision.action, "add")

    def test_old_runner_cannot_clear_paused_request(self):
        self.crafting()
        request = self.engine._craft_request
        self.engine.pause_task()
        run_crafting(self.engine, request, 0)
        self.assertIs(self.engine._craft_request, request)


if __name__ == "__main__":
    unittest.main()
