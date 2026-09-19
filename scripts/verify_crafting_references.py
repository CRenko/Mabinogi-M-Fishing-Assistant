"""用原始截图验证四类加工及缩放。仅离线识别，不连接游戏。"""
import argparse
import logging
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)
import cv2
import numpy as np
from build_crafting_templates import SOURCES
from fishing_assistant.crafting import RECIPES
from fishing_assistant.crafting_vision import CraftVision
sys.excepthook = sys.__excepthook__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    images = {key: cv2.imdecode(np.fromfile(args.source_dir/name, dtype=np.uint8), cv2.IMREAD_COLOR) for key,name in SOURCES.items()}
    vision = CraftVision()
    checked = 0
    for factor in (2/3, .75, 1, 4/3, 1.6, 2):
        for key, slots in (("wood", ("complete",)*4), ("metal", ("busy",)*4),
                           ("cloth", ("complete","complete","empty","empty")), ("leather", ("empty",)*4)):
            frame = cv2.resize(images[key], None, fx=factor, fy=factor)
            for recipe in (r for r in RECIPES if r.category == key):
                view = vision.inspect(frame, recipe.key)
                assert view.category == key and view.slots == slots and view.recipe_point, (factor, recipe.key, view)
                # 分类内按列表顺序，名称相近也必须落在各自卡片上。
                index = [r.key for r in RECIPES if r.category == key].index(recipe.key)
                expected_x = (790 + index*190)*factor
                assert abs(view.recipe_point[0]-expected_x) < 45*factor, (recipe.key, view.recipe_point)
                checked += 1
        detail = vision.inspect(cv2.resize(images["detail"], None, fx=factor, fy=factor), "wood")
        assert detail.dialog_open and detail.dialog_recipe == "wood" and detail.slots == ("empty",)*4 and detail.process_point, detail
        wrong = vision.inspect(cv2.resize(images["detail"], None, fx=factor, fy=factor), "wood_plus")
        assert wrong.dialog_recipe != "wood_plus", wrong
        assert vision.inspect(cv2.resize(images["insufficient"], None, fx=factor, fy=factor), "wood").insufficient
        assert vision.inspect(cv2.resize(images["result"], None, fx=factor, fy=factor), "wood").result
        checked += 4
    # 模拟 16:10 / 宽屏：顶部配方和底部队列分别锚定，不拉伸文字。
    for height in (1200, 1440):
        original = images["cloth"]
        frame = np.zeros((height, original.shape[1], 3), np.uint8)
        frame[:550] = original[:550]
        frame[-350:] = original[-350:]
        view = vision.inspect(frame, "cloth")
        assert view.category == "cloth" and view.slots == ("complete","complete","empty","empty"), view
        checked += 1
    print(f"PASS: {checked} reference/scale/layout checks")


if __name__ == "__main__":
    main()
