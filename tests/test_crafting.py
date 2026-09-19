"""自动制作的计数、安全等待、互斥与停止回归测试；不发送真实游戏按键。"""
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from fishing_assistant.crafting import CraftOptions, CraftSession, CraftView, RECIPE_BY_KEY
from fishing_assistant.config import AppConfig, _config_from_raw
from fishing_assistant.engine import FishingEngine

EMPTY = CraftView("wood", ("empty",)*4, (800,400), (170,790))


class CraftSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.session = CraftSession(CraftOptions(count=4), 0)

    def feed(self, view, ticks=3):
        for _ in range(ticks):
            self.now += 1
            decision = self.session.step(view, self.now)
            if decision.action != "wait" or self.session.finished:
                return decision
        return decision

    def add(self, occupied):
        previous = self.session.submitted
        view = replace(EMPTY, slots=("busy",)*occupied+("empty",)*(4-occupied))
        self.assertEqual(self.feed(view).action, "open_recipe")
        detail = replace(view, recipe_point=None, dialog_open=True, dialog_recipe="wood", process_point=(1530,930))
        self.assertEqual(self.feed(detail).action, "add")
        self.assertEqual(self.session.submitted, previous)
        after = replace(view, slots=("busy",)*(occupied+1)+("empty",)*(3-occupied))
        self.feed(after, ticks=2)
        self.assertEqual(self.session.submitted, previous+1)
        return after

    def collect(self, count):
        done = replace(EMPTY, slots=("complete",)*count+("empty",)*(4-count))
        self.assertEqual(self.feed(done).action, "collect")
        result = CraftView(result=True)
        self.assertEqual(self.feed(result).action, "confirm")
        # 弹窗动画延迟时不重复空格、不误报新的领取弹窗。
        self.feed(result)
        self.feed(EMPTY, ticks=2)

    def test_catalog_uses_requested_per_item_times(self):
        self.assertEqual({k:v.seconds for k,v in RECIPE_BY_KEY.items()},
            dict(wood=90, wood_plus=720, iron_ore=60, iron_iron_ore=60, steel=600,
                 cloth=90, silk=180, cloth_plus=720, leather=60, leather_plus=600))

    def test_full_queue_waits_for_four_percentages_not_elapsed_time(self):
        for n in range(4):
            self.add(n)
        self.assertEqual(self.session.submitted, 4)
        # 持续看到加工中，预估时间过去也不领；并非 1000 秒没收到画面。
        for _ in range(400):
            self.feed(replace(EMPTY, slots=("complete",)*3+("busy",)))
        self.assertEqual(self.feed(replace(EMPTY, slots=("complete",)*3+("busy",))).action, "wait")
        self.assertFalse(self.session.finished)
        self.collect(4)
        self.assertTrue(self.session.finished)
        self.assertEqual(self.session.collected, 4)

    def test_one_item_limit_does_not_fill_remaining_slots(self):
        self.session = CraftSession(CraftOptions(count=1), 0)
        self.add(0)
        self.collect(1)
        self.assertTrue(self.session.finished)
        self.assertEqual(self.session.submitted, 1)

    def test_six_items_two_batches_exact_count(self):
        self.session = CraftSession(CraftOptions(count=6), 0)
        for n in range(4):
            self.add(n)
        self.collect(4)
        # 返回主界面时已打开下一轮材料详情。
        detail = replace(EMPTY, dialog_open=True, dialog_recipe="wood", process_point=(1500,920))
        self.assertEqual(self.feed(detail).action, "add")
        self.feed(replace(EMPTY, slots=("busy","empty","empty","empty")), ticks=2)
        self.add(1)
        self.collect(2)
        self.assertTrue(self.session.finished)
        self.assertEqual((self.session.submitted, self.session.collected), (6,6))

    def test_unstable_view_also_has_timeout(self):
        for n in range(30):
            self.now += 1
            view = replace(EMPTY, slots=("unknown", "busy" if n % 2 else "empty", "empty", "empty"))
            self.session.step(view, self.now)
        self.assertEqual(self.session.phase, "error")

    def test_exhausted_materials_drains_partial_queue(self):
        self.session = CraftSession(CraftOptions(mode="exhaust"), 0)
        view = self.add(0)
        self.assertEqual(self.feed(view).action, "open_recipe")
        detail = replace(view, dialog_open=True, dialog_recipe="wood", insufficient=True)
        self.assertEqual(self.feed(detail).action, "close_dialog")
        self.feed(view)
        self.collect(1)
        self.assertTrue(self.session.finished)
        self.assertEqual(self.session.collected, 1)

    def test_pending_add_insufficient_does_not_count_unadded_item(self):
        self.assertEqual(self.feed(EMPTY).action, "open_recipe")
        detail = replace(EMPTY, dialog_open=True, dialog_recipe="wood", process_point=(1500,920))
        self.assertEqual(self.feed(detail).action, "add")
        self.assertEqual(self.feed(replace(detail, insufficient=True)).action, "close_dialog")
        self.feed(EMPTY)
        self.assertEqual(self.session.submitted, 0)
        self.assertTrue(self.session.finished)

    def test_no_duplicate_space_when_add_ack_is_missing(self):
        self.feed(EMPTY)
        detail = replace(EMPTY, dialog_open=True, dialog_recipe="wood", process_point=(1500,920))
        self.assertEqual(self.feed(detail).action, "add")
        self.assertEqual(self.feed(detail).action, "wait")
        self.now += 20
        self.feed(detail)
        self.assertTrue(self.session.finished)
        self.assertEqual(self.session.submitted, 0)

    def test_category_and_recipe_mismatch_never_add(self):
        self.feed(replace(EMPTY, category="metal"))
        self.assertTrue(self.session.finished)
        self.session = CraftSession(CraftOptions(), self.now)
        self.feed(EMPTY)
        decision = self.feed(replace(EMPTY, dialog_open=True, dialog_recipe="wood_plus", process_point=(1500,920)))
        self.assertEqual(decision.action, "wait")
        self.assertEqual(self.session.phase, "error")

    def test_unknown_slot_is_not_empty_or_complete(self):
        view = replace(EMPTY, slots=("complete",)*3+("unknown",))
        self.feed(view)
        self.assertEqual(self.session.submitted, 0)
        self.now += 25
        self.feed(view)
        self.assertEqual(self.session.phase, "error")

    def test_unclear_queue_identifies_slots_and_still_sends_no_input(self):
        view = replace(EMPTY, slots=("unknown", "busy", "unknown", "empty"))
        self.assertEqual(self.feed(view).action, "wait")
        self.assertIn("第 1、3 格", self.session.message)
        self.assertEqual(self.session.submitted, 0)

    def test_incomplete_queue_explains_clipped_edges(self):
        view = replace(EMPTY, queue_complete=False)
        self.assertEqual(self.feed(view).action, "wait")
        self.assertIn("边缘", self.session.message)

    def test_missing_recipe_times_out_not_infinite_poll(self):
        view = replace(EMPTY, recipe_point=None)
        self.feed(view)
        self.now += 25
        self.feed(view)
        self.assertEqual(self.session.phase, "error")

    def test_existing_full_queue_not_counted_as_new(self):
        self.collect(4)
        self.assertEqual(self.session.collected, 0)
        self.assertFalse(self.session.finished)
        self.assertEqual(self.session.phase, "await_dialog")

    def test_reject_invalid_options_and_config_fallback(self):
        for options in (CraftOptions(recipe="advanced_wood"), CraftOptions(mode="auto"), CraftOptions(count=0), CraftOptions(count=3.5)):
            with self.assertRaises(ValueError):
                options.validate()
        config = _config_from_raw(dict(crafting_recipe="bad", crafting_count="NaN", crafting_mode="bad"))
        self.assertEqual((config.crafting_recipe, config.crafting_mode, config.crafting_count), ("wood","count",4))


class CraftEngineSafetyTests(unittest.TestCase):
    def setUp(self):
        with patch("fishing_assistant.engine.load_config", return_value=AppConfig()):
            self.engine = FishingEngine()
        self.target = Mock(handle=123, title="瑪奇 Mobile", width=1920, height=1080)

    def start(self):
        with patch("fishing_assistant.window_target.get_window_info", return_value=self.target), patch("fishing_assistant.window_target.OkWindowBackend.available", return_value=True):
            return self.engine.start_crafting(CraftOptions(), 123)

    def test_no_fishing_calibration_needed_and_stop_invalidates_actions(self):
        self.assertTrue(self.start())
        generation = self.engine._interrupt_generation
        self.assertTrue(self.engine.is_crafting())
        self.assertFalse(self.engine.request_inventory_cleanup_test())
        self.engine.set_monitoring(False)
        self.assertFalse(self.engine._operation_active(generation))
        self.assertIsNone(self.engine._craft_request)
        self.assertFalse(self.engine.is_monitoring())

    def test_fishing_busy_rejects_crafting_and_keeps_fishing(self):
        self.engine._enabled.set()
        self.assertFalse(self.start())
        self.assertTrue(self.engine.is_monitoring())
        self.assertIsNone(self.engine._craft_request)

    def test_crafting_does_not_fall_back_if_ok_unavailable(self):
        with patch("fishing_assistant.window_target.get_window_info", return_value=self.target), patch("fishing_assistant.window_target.OkWindowBackend.available", return_value=False):
            self.assertFalse(self.engine.start_crafting(CraftOptions(), 123))
        self.assertFalse(self.engine.is_monitoring())
        self.assertIsNone(self.engine._craft_request)

    def test_f9_and_crafting_cannot_overlap(self):
        self.engine._debug_capture_lock.acquire()
        try:
            self.assertFalse(self.start())
        finally:
            self.engine._debug_capture_lock.release()
        self.assertTrue(self.start())
        self.assertFalse(self.engine.request_debug_capture())
        self.assertTrue(self.engine.is_crafting())
        self.engine.set_monitoring(False)

    def test_close_cancels_crafting(self):
        self.start()
        generation = self.engine._interrupt_generation
        self.engine.close()
        self.assertFalse(self.engine._operation_active(generation))


if __name__ == "__main__":
    unittest.main()
