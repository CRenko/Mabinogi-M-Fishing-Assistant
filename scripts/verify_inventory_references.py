"""用用户的原始背包截图离线检查入口。不会打开游戏、发送按键或整理物品。"""
import argparse
import logging
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)
import cv2
import numpy as np
from fishing_assistant.inventory_cleanup import InventoryCleanupVision as Vision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-screen", type=Path, required=True)
    args = parser.parse_args()
    original = cv2.imdecode(np.fromfile(args.inventory_screen, np.uint8),cv2.IMREAD_COLOR)
    assert original is not None
    checks = 0
    for scale in (2/3,.75,1,4/3,1.6,2):
        frame = cv2.resize(original,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
        match = Vision.find_inventory_tidy(frame)
        assert match is not None, (scale,Vision.last_scores)
        assert abs(match.center[0]/scale-1775)<35 and abs(match.center[1]/scale-798)<25, (scale,match)
        assert Vision.inspect_simple_screen(frame) is None, (scale,"inventory mistaken for simple cleanup")
        print(f"scale={scale:.3f}, OK entry={match.confidence:.3f}, point={match.center}")
        checks += 2
    # 16:10 与超宽屏：保持右下角 UI 尺寸和锚定方式，不把文字横向拉伸。
    for width,height in ((1920,1200),(2560,1080)):
        frame = np.zeros((height,width,3),np.uint8)
        crop = original[600:,1300:]
        frame[-crop.shape[0]:,-crop.shape[1]:] = crop
        match = Vision.find_inventory_tidy(frame)
        assert match is not None,(width,height,Vision.last_scores)
        checks += 1
    assert Vision.find_inventory_tidy(np.zeros((1080,1920,3),np.uint8)) is None
    print(f"Inventory reference verification passed: {checks+1} checks.")


if __name__ == "__main__":
    main()
