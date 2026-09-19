"""从用户提供的加工界面提取文字/空槽特征；不保留角色、物品图案或账号信息。

开发用法：python scripts/build_crafting_templates.py --source-dir <截图目录>
"""
from pathlib import Path
import argparse
import cv2
import numpy as np

SOURCES = {
    "wood": "codex-clipboard-82d0e57e-55e7-4a13-a427-d44283d44c6c.png",
    "result": "codex-clipboard-44fd0e53-22bf-41ec-a765-534e0406604a.png",
    "detail": "codex-clipboard-d89cb826-6c0f-49c1-b9e5-4ddeb0a10b72.png",
    "insufficient": "codex-clipboard-1f0e5ca0-4511-4151-9658-8a1fa2c41322.png",
    "metal": "codex-clipboard-c6ccb8b9-bed0-44ec-9b61-9f39d09fa694.png",
    "cloth": "codex-clipboard-68901dcf-ce42-4624-b71c-4af22980a1fa.png",
    "leather": "codex-clipboard-1806baa8-64b1-4b97-b37a-ac33c2ac77e0.png",
}
# 坐标只用于制作识别模板。运行时通过 OK 多尺度定位，不固定点击截图坐标。
CROPS = {
    "category_wood": ("wood", (33, 35, 189, 78)),
    "category_metal": ("metal", (23, 19, 184, 65)),
    "category_cloth": ("cloth", (28, 28, 188, 75)),
    "category_leather": ("leather", (30, 26, 190, 73)),
    "recipe_wood": ("wood", (771, 391, 821, 419)),
    "recipe_wood_plus": ("wood", (953, 391, 1018, 419)),
    "recipe_iron_ore": ("metal", (733, 375, 847, 405)),
    "recipe_iron_iron_ore": ("metal", (912, 375, 1041, 405)),
    "recipe_steel": ("metal", (1141, 375, 1190, 405)),
    "recipe_cloth": ("cloth", (769, 386, 818, 415)),
    "recipe_silk": ("cloth", (958, 386, 1008, 415)),
    "recipe_cloth_plus": ("cloth", (1142, 386, 1210, 415)),
    "recipe_leather": ("leather", (772, 384, 822, 413)),
    "recipe_leather_plus": ("leather", (958, 384, 1020, 413)),
    # 更长的相近名称只用于排除误选，不向用户开放未给定时间的配方。
    "recipe_advanced_wood": ("wood", (1127, 391, 1220, 419)),
    "recipe_advanced_wood_plus": ("wood", (1310, 391, 1425, 419)),
    "recipe_alloy": ("metal", (1306, 375, 1408, 405)),
    "recipe_special_steel": ("metal", (1498, 375, 1602, 405)),
    "recipe_advanced_cloth": ("cloth", (1312, 386, 1414, 415)),
    "recipe_advanced_silk": ("cloth", (1501, 386, 1605, 415)),
    "recipe_advanced_cloth_plus": ("cloth", (1690, 386, 1810, 415)),
    "recipe_advanced_leather": ("leather", (1126, 384, 1220, 413)),
    "recipe_advanced_leather_plus": ("leather", (1310, 384, 1425, 413)),
    "collect": ("wood", (128, 779, 219, 808)),
    "percent_100": ("wood", (132, 899, 196, 929)),
    "percent_100_cloth": ("cloth", (128, 894, 195, 926)),
    "percent_100_silk": ("cloth", (250, 894, 316, 926)),
    "percent": ("metal", (161, 886, 184, 913)),
    "empty": ("leather", (107, 829, 218, 941)),
    "empty_cloth": ("cloth", (345, 828, 461, 944)),
    "empty_cloth_right": ("cloth", (466, 828, 581, 944)),
    "result": ("result", (872, 266, 1065, 318)),
    "confirm": ("result", (930, 900, 995, 936)),
    "process": ("detail", (1500, 909, 1565, 947)),
    "detail_heading": ("detail", (1447, 595, 1537, 626)),
    "insufficient": ("insufficient", (900, 81, 1024, 111)),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    images = {}
    for key, name in SOURCES.items():
        images[key] = cv2.imdecode(np.fromfile(args.source_dir / name, dtype=np.uint8), cv2.IMREAD_COLOR)
        if images[key] is None:
            raise ValueError(f"无法读取 {name}")
    output = Path(__file__).resolve().parents[1] / "fishing_assistant/assets/crafting"
    output.mkdir(parents=True, exist_ok=True)
    for name, (source, (left, top, right, bottom)) in CROPS.items():
        crop = images[source][top:bottom, left:right]
        ok, png = cv2.imencode(".png", crop)
        if not ok or not crop.size:
            raise ValueError(name)
        png.tofile(output / f"{name}.png")
    print(f"已提取 {len(CROPS)} 个文字及空槽模板。")


if __name__ == "__main__":
    main()
