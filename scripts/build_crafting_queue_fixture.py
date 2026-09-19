"""从用户五格队列截图保存无账号信息的回归样本和 OK 圆环模板。"""
import argparse
from pathlib import Path
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-reference", type=Path)
    parser.add_argument("--empty-reference", type=Path, help="炉子背景下五个空槽的 1903×960 问题截图")
    args = parser.parse_args()
    if not args.queue_reference and not args.empty_reference:
        parser.error("至少提供一种队列截图")
    root = Path(__file__).resolve().parents[1]
    if args.empty_reference:
        image = cv2.imdecode(np.fromfile(args.empty_reference, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (960, 1903):
            raise ValueError("需要所提供的 1903×960 五个空槽问题截图")
        # 仅保留领取文字、空槽和附近炉子；不保存助手窗口、角色或聊天信息。
        cv2.imencode(".png", image[625:935, 90:590])[1].tofile(
            root / "tests/fixtures/crafting_queue_empty_furnace.png")
        print("Saved empty-slot furnace regression fixture.")
    if not args.queue_reference:
        return
    image = cv2.imdecode(np.fromfile(args.queue_reference, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (342, 525):
        raise ValueError("需要所提供的 525×342 五格队列截图")
    cv2.imencode(".png", image)[1].tofile(root / "tests/fixtures/crafting_queue_five.png")
    # 运行时仅匹配环带遮罩，不使用内部材料图案或百分比判定容量。
    cv2.imencode(".png", image[92:204, 34:146])[1].tofile(root / "fishing_assistant/assets/crafting/queue_ring.png")
    cv2.imencode(".png", image[158:189, 56:125])[1].tofile(root / "fishing_assistant/assets/crafting/percent_100_iron.png")
    print("Saved five-slot fixture and OK ring template.")


if __name__ == "__main__":
    main()
