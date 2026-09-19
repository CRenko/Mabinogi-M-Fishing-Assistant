"""桌面端公共术语。仅提供显示文案，不改变配置键或后端选择。"""

RUN_MODE_LABELS = {
    "window": "后台运行（推荐）",
    "screen": "前台运行",
}

WINDOW_CAPTURE_LABELS = {
    "ok": "Windows Graphics Capture（推荐）",
    "printwindow": "PrintWindow（兼容）",
}
WINDOW_CAPTURE_DESCRIPTIONS = {
    "ok": "使用 Windows Graphics Capture（WGC）获取目标窗口画面，由 ok-script 提供捕获组件。",
    "printwindow": "使用 Windows PrintWindow 接口获取目标窗口画面，适用于捕获兼容性排查。",
}
WINDOW_INPUT_LABEL = "窗口消息（PostMessage）"
WINDOW_INPUT_DESCRIPTION = (
    "两种捕获方式均通过 PostMessage 向选定窗口发送键鼠消息，不移动系统鼠标。"
    "是否响应取决于游戏对窗口消息的支持；切换捕获方式不会改变输入方式。"
)

ICON_RECOGNITION_LABELS = {
    "ok": "图像模板匹配（推荐）",
    "pixel": "像素识别（旧版兼容）",
}
ICON_MATCH_SCORE_LABEL = "图标匹配相似度"
