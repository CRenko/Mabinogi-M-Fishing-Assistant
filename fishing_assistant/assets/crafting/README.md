# 加工识别模板

模板从本次提供的游戏界面截图中裁切，用于 OK FeatureSet 识别加工分类、材料名称、百分比、空队列、按钮文字和提示。没有保存完整游戏截图或账户信息区域。

- `scripts/build_crafting_templates.py`：记录原始截图文件名及裁切范围，可通过 `--source-dir` 指定截图目录重新生成。
- `scripts/verify_crafting_references.py`：用原始截图进行离线识别、缩放和布局回归，不连接游戏。
- `recipe_advanced_*`、`recipe_alloy` 和 `recipe_special_steel` 仅用来排除相近名称，避免误认详情；不表示已支持自动制作这些配方。

裁切坐标只用于生成模板。运行时通过文字锚点和缩放定位，不把示例截图的坐标直接当作游戏点击坐标。游戏 UI 图像版权归原权利人所有。
