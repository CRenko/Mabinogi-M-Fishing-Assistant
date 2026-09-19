"""从现有背包截图裁切固定文字/开关，供 OK 识别；不保存玩家物品信息。"""
import argparse
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    result = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if result is None:
        raise ValueError(f"无法读取 {path}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-screen", type=Path, required=True)
    args = parser.parse_args()
    assets = ROOT / "fishing_assistant/assets"
    original = read(args.inventory_screen)
    assert original.shape[:2] == (1003, 1918), original.shape
    sources = {
        "inventory_tidy_text.png": read(assets / "inventory_tidy_anchor.png")[24:50, 33:85],
        "inventory_items_tab.png": original[929:960, 1438:1499],
        "cleanup_bold_on.png": read(ROOT / "tests/fixtures/cleanup_simple_on.png")[118:156, 34:98],
        "cleanup_bold_off.png": read(ROOT / "tests/fixtures/cleanup_simple_off.png")[126:164, 35:99],
    }
    for name, crop in sources.items():
        assert crop.size
        cv2.imencode(".png", crop)[1].tofile(assets / name)
        print(name, crop.shape)


if __name__ == "__main__":
    main()
