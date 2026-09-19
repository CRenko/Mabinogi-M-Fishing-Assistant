"""队列容量从一格起；真实五格截图和合成扩容场景不连接游戏。"""
from dataclasses import replace
from pathlib import Path
import unittest

import cv2
import numpy as np

from fishing_assistant.constants import resource_path
from fishing_assistant.config import _config_from_raw
from fishing_assistant.features.crafting.model import CraftOptions, CraftSession, CraftView
from fishing_assistant.features.crafting.recognition import CraftVision
from fishing_assistant.window_geometry import ClientFrame, ClientGeometry


FIXTURE = Path(__file__).parent / "fixtures/crafting_queue_five.png"
EMPTY_FIXTURE = FIXTURE.with_name("crafting_queue_empty_furnace.png")


def furnace_frame():
    """保留问题截图的槽位与炉子背景，用无账号信息的文字模板补齐主界面。"""
    frame = np.full((960, 1903, 3), 35, np.uint8)
    queue = cv2.imread(str(EMPTY_FIXTURE))
    frame[625:935, 90:590] = queue
    assets = resource_path("fishing_assistant", "assets", "crafting")
    for key, x, y in (("category_metal", 24, 14), ("recipe_iron_ore", 734, 375)):
        image = cv2.imread(str(assets / (key + ".png")))
        frame[y:y+image.shape[0], x:x+image.shape[1]] = image
    return frame


def make_frame(capacity=5, *, actual=False, width=1920, height=1080, states=None):
    reference = cv2.imread(str(FIXTURE))
    frame = np.full((height, width, 3), 35, np.uint8)
    assets = resource_path("fishing_assistant", "assets", "crafting")
    def paste(image, x, y):
        frame[y:y+image.shape[0], x:x+image.shape[1]] = image
    paste(cv2.imread(str(assets / "category_metal.png")), 24, 24)
    paste(cv2.imread(str(assets / "recipe_iron_ore.png")), 734, 375)
    rows = (capacity+3)//4
    x, y = 70, height-342-25-(rows-2)*122
    if actual:
        paste(reference, x, y)
    else:
        paste(reference[20:92, 32:190], x+32, y+20)
        for index in range(capacity):
            state = states[index] if states else "complete"
            circle = reference[92:204, 34:146].copy()
            if state == "empty":
                circle = cv2.imread(str(assets / "empty.png"))
            elif state in {"busy", "unknown"}:
                # 模拟进度文字暂时被特效遮挡，但保留槽位的上半圆环。
                circle[77:101, 39:108] = 35
                if state == "busy":
                    percent = cv2.imread(str(assets / "percent.png"))
                    circle[69:69+percent.shape[0], 73:73+percent.shape[1]] = percent
            row, col = divmod(index, 4)
            paste(circle, x+34+col*122, y+92+row*122)
    return frame


class QueueVisionTests(unittest.TestCase):
    def test_aspect_ratios_preserve_text_and_restore_click_to_client_pixels(self):
        # 调整客户区长宽比而不是拉伸文字；队列贴底、配方贴左侧面板。
        for width,height,base_width,base_height in (
            (1366,768,1920,1080), (1920,1080,1920,1080),
            (2560,1600,1920,1200), (3440,1440,2580,1080),
            (3840,2160,1920,1080), (5120,1440,3840,1080),
        ):
            with self.subTest(size=(width,height)):
                image = cv2.resize(make_frame(width=base_width,height=base_height), (width,height))
                view = CraftVision().inspect(image, "iron_ore")
                self.assertEqual(view.category, "metal")
                self.assertEqual(view.slots, ("complete",)*5)
                self.assertTrue(view.queue_complete)
                self.assertIsNotNone(view.recipe_point)
                geometry = ClientGeometry(123,"game",-2000,30,width,height,width+20,height+40,1.5)
                point = ClientFrame(image,geometry).client_point(view.recipe_point)
                self.assertAlmostEqual(point[0],790*width/base_width,delta=5)
                self.assertAlmostEqual(point[1],390*height/base_height,delta=5)

    def test_real_empty_slots_over_furnace_across_resolutions_and_dimming(self):
        frame = furnace_frame()
        vision = CraftVision()
        for width in (1280, 1903, 1940, 2560, 3840):
            for brightness in (1.0, .4):
                with self.subTest(width=width, brightness=brightness):
                    sample = cv2.resize(frame, (width, round(960*width/1903)))
                    sample = (sample*brightness).astype(np.uint8)
                    view = vision.inspect(sample, "iron_ore")
                    self.assertEqual(view.slots, ("empty",)*5, view.detail)
                    self.assertTrue(view.queue_complete)
                    self.assertIsNotNone(view.recipe_point)

    def test_real_empty_queue_reaches_add_flow_without_game_input(self):
        view = CraftVision().inspect(furnace_frame(), "iron_ore")
        session = CraftSession(CraftOptions(recipe="iron_ore", count=5), 0)
        decision = None
        for now in (1, 2, 3):
            decision = session.step(view, now)
            if decision.action != "wait":
                break
        self.assertEqual(decision.action, "open_recipe")
        self.assertEqual(session.queue_capacity, 5)
        self.assertEqual(session.submitted, 0)

    def test_occupied_slots_without_readable_percentage_are_never_empty(self):
        # 不降低既有的完成要求：只看见圆环和材料仍应为 unknown。
        for state in ("unknown", "busy", "complete"):
            view = CraftVision().inspect(make_frame(states=(state,)*5), "iron_ore")
            self.assertEqual(view.slots, (state,)*5, view.detail)

    def test_original_five_slot_screenshot_and_resolutions(self):
        frame = make_frame(actual=True)
        vision = CraftVision()
        for scale in (2/3,1,4/3,2):
            with self.subTest(scale=scale):
                view = vision.inspect(cv2.resize(frame,None,fx=scale,fy=scale), "iron_ore")
                self.assertEqual(view.slots, ("complete",)*5, view.detail)
                self.assertTrue(view.queue_complete)
                self.assertEqual(view.category, "metal")

    def test_capacity_starts_at_one_and_extends_to_multiple_rows(self):
        for capacity in (1,2,3,4,5,6,8,9,12):
            with self.subTest(capacity=capacity):
                view = CraftVision().inspect(make_frame(capacity), "iron_ore")
                self.assertEqual(view.slots, ("complete",)*capacity, view.detail)
                self.assertTrue(view.queue_complete)

    def test_fifth_unknown_ring_is_not_dropped_or_called_complete(self):
        view = CraftVision().inspect(make_frame(states=("complete",)*4+("unknown",)), "iron_ore")
        self.assertEqual(view.slots, ("complete",)*4+("unknown",), view.detail)

    def test_all_empty_one_and_five_slot_queues(self):
        for capacity in (1,5):
            view = CraftVision().inspect(make_frame(capacity,states=("empty",)*capacity), "iron_ore")
            self.assertEqual(view.slots, ("empty",)*capacity, view.detail)

    def test_fifth_busy_is_not_finished(self):
        view = CraftVision().inspect(make_frame(states=("complete",)*4+("busy",)), "iron_ore")
        self.assertEqual(view.slots, ("complete",)*4+("busy",), view.detail)

    def test_manual_capacity_cannot_hide_extra_slot_and_missing_slot_is_unknown(self):
        vision = CraftVision()
        self.assertEqual(len(vision.inspect(make_frame(actual=True), "iron_ore",queue_capacity=4).slots),5)
        view = vision.inspect(make_frame(4), "iron_ore", queue_capacity=5)
        self.assertEqual(view.slots[-1], "unknown")
        self.assertEqual(len(view.slots),5)

    def test_cropped_bottom_slot_is_not_a_complete_queue(self):
        frame = make_frame(actual=True)[:-60]
        view = CraftVision().inspect(frame,"iron_ore",queue_capacity=5)
        self.assertFalse(view.queue_complete)


class QueueSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0

    def feed(self, session, view, ticks=3):
        for _ in range(ticks):
            self.now += 1
            decision = session.step(view,self.now)
            if decision.action != "wait" or session.finished:
                break
        return decision

    def test_full_cycles_from_one_through_expanded_capacity(self):
        for capacity in (1,2,4,5,6,9):
            with self.subTest(capacity=capacity):
                session = CraftSession(CraftOptions(count=capacity),self.now)
                empty = CraftView("wood",("empty",)*capacity,(800,400),(170,790))
                for occupied in range(capacity):
                    view = replace(empty, slots=("busy",)*occupied+("empty",)*(capacity-occupied))
                    self.assertEqual(self.feed(session,view).action,"open_recipe")
                    detail = replace(view,dialog_open=True,dialog_recipe="wood",process_point=(1500,920))
                    self.assertEqual(self.feed(session,detail).action,"add")
                    added = replace(view,slots=("busy",)*(occupied+1)+("empty",)*(capacity-occupied-1))
                    self.feed(session,added,ticks=2)
                self.assertEqual(session.queue_capacity,capacity)
                self.assertEqual(session.submitted,capacity)
                almost = replace(empty,slots=("complete",)*(capacity-1)+("busy",))
                self.assertEqual(self.feed(session,almost).action,"wait")
                self.assertEqual(self.feed(session,replace(empty,slots=("complete",)*capacity)).action,"collect")
                self.assertEqual(self.feed(session,CraftView(result=True)).action,"confirm")
                self.feed(session,empty)
                self.assertTrue(session.finished)
                self.assertEqual(session.collected,capacity)

    def test_capacity_is_locked_and_missing_fifth_slot_never_triggers_collect(self):
        session = CraftSession(CraftOptions(count=1),0)
        busy = CraftView("wood",("busy",)*5,(800,400),(170,790))
        self.feed(session,busy)
        self.assertEqual(session.queue_capacity,5)
        missing = replace(busy,slots=("complete",)*4)
        self.assertEqual(self.feed(session,missing).action,"wait")
        self.assertEqual(session.slots[-1],"unknown")
        self.now += 22
        self.feed(session,missing)
        self.assertEqual(session.phase,"error")

    def test_one_remaining_operation_does_not_fill_five_slots(self):
        session = CraftSession(CraftOptions(count=1),0)
        empty = CraftView("wood",("empty",)*5,(800,400),(170,790))
        self.feed(session,empty)
        self.feed(session,replace(empty,dialog_open=True,dialog_recipe="wood",process_point=(1500,920)))
        added = replace(empty,slots=("busy",)+("empty",)*4)
        self.feed(session,added)
        self.assertEqual(self.feed(session,added).action,"wait")
        self.assertEqual(self.feed(session,replace(added,slots=("complete",)+("empty",)*4)).action,"collect")
        self.assertEqual(session.submitted,1)

    def test_manual_capacity_mismatch_or_incomplete_view_never_operates(self):
        for view in (CraftView("wood",("complete",)*5,(800,400),(170,790)),
                     CraftView("wood",("complete",)*4,(800,400),(170,790),queue_complete=False)):
            session = CraftSession(CraftOptions(queue_capacity=4),self.now)
            self.assertEqual(self.feed(session,view).action,"wait")
            self.assertEqual(session.submitted,0)

    def test_old_config_defaults_to_auto_and_capacity_is_not_iteration_count(self):
        self.assertEqual(_config_from_raw({}).crafting_queue_capacity,0)
        for capacity in (1,5,12):
            config = _config_from_raw({"crafting_queue_capacity":capacity,"crafting_count":9})
            self.assertEqual((config.crafting_queue_capacity,config.crafting_count),(capacity,9))
        for invalid in (-1,33,"NaN",None):
            self.assertEqual(_config_from_raw({"crafting_queue_capacity":invalid}).crafting_queue_capacity,0)


if __name__ == "__main__":
    unittest.main()
