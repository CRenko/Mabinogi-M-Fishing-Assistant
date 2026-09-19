"""提取铁锭详情的文字锚点；裁切坐标只用于建素材，不用于运行时点击。"""
import argparse
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DETAIL_SOURCE = "codex-clipboard-5d2f1b45-d9d1-457b-8674-62a7426b0491.png"
OVERVIEW_SOURCE = "codex-clipboard-d175f3d5-359c-42e7-9ff1-bc7772ce8aa1.png"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    assets = ROOT / "fishing_assistant/assets/crafting"
    def read(path):
        image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"无法读取 {path}")
        return image
    def save(path, image):
        assert image.size
        ok, data = cv2.imencode('.png', image)
        assert ok
        data.tofile(path)
    detail = read(args.source_dir / DETAIL_SOURCE)
    overview = read(args.source_dir / OVERVIEW_SOURCE)
    save(assets/'detail_iron.png', detail[357:394, 1292:1360])
    save(assets/'ingredient_ore.png', detail[718:750, 1468:1519])
    # 列表模板中的“鐵礦石”，不包含“鐵錠”与括号。
    label = read(assets/'recipe_iron_iron_ore.png')
    save(assets/'ingredient_iron_ore.png', label[:, 54:118])
    # 回归素材仅保留加工标题、配方文字、队列和详情文字；去掉助手与账号信息。
    for name, frame, regions in (
        ('crafting_iron_overview.png', overview, ((15,20,245,90),(710,370,1060,430),(90,620,590,965))),
        ('crafting_iron_detail.png', detail, ((15,15,245,85),(90,620,590,945),
            (1275,345,1390,400),(1435,568,1560,608),(1455,712,1530,756),(1480,880,1590,935))),
    ):
        fixture = np.full_like(frame, 25)
        for x1,y1,x2,y2 in regions:
            fixture[y1:y2,x1:x2] = frame[y1:y2,x1:x2]
        save(ROOT/'tests/fixtures'/name, fixture)
    print('已生成 3 个铁锭文字模板和 2 张脱敏回归素材。')


if __name__ == '__main__':
    main()
