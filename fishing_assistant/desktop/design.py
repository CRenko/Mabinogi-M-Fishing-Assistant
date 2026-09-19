"""桌面字体与排版令牌；尺寸使用 Qt 逻辑像素，由 Qt 处理系统 DPI 缩放。"""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLayout


FONT_FAMILIES = ("Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei")
BODY_SIZE = 14
SECONDARY_SIZE = 13
CAPTION_SIZE = 12
CARD_TITLE_SIZE = 16
PAGE_TITLE_SIZE = 24
CARD_PADDING = 16
SECTION_SPACING = 12


def ui_font(size: int = BODY_SIZE) -> QFont:
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(size)
    return font


def configure_card_layout(layout: QLayout) -> None:
    layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
    layout.setSpacing(SECTION_SPACING)


# 字体独立于主题颜色。不要在页面中再写固定字号覆盖这些层级。
TYPOGRAPHY_STYLE = f"""
QWidget {{ font-family: 'Segoe UI', 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: {BODY_SIZE}px; font-weight: 400; }}
QLabel#pageTitle {{ font-size: {PAGE_TITLE_SIZE}px; font-weight: 600; }}
QLabel#cardTitle {{ font-size: {CARD_TITLE_SIZE}px; font-weight: 600; }}
QLabel#formLabel, QLabel#fieldLabel {{ font-size: {BODY_SIZE}px; font-weight: 500; }}
QLabel#cardHint, QLabel#helper, QLabel#pageSubtitle {{ font-size: {SECONDARY_SIZE}px; font-weight: 400; }}
QLabel#helpStep, QLabel#safetyWarning {{ font-size: {BODY_SIZE}px; font-weight: 400; }}
QLabel#metricValue {{ font-size: 22px; font-weight: 600; }}
QLabel#metricCaption, QLabel#eyebrow, QLabel#navSection {{ font-size: {CAPTION_SIZE}px; font-weight: 400; }}
QLabel#brandTitle {{ font-size: {BODY_SIZE}px; font-weight: 600; }}
QLabel#brandSubtitle {{ font-size: {CAPTION_SIZE}px; font-weight: 400; letter-spacing: 0; }}
QLabel#backendModeBadge, QLabel#statusChip, QLabel#runtimeStateChip {{ font-size: {SECONDARY_SIZE}px; font-weight: 500; }}
QLabel#timingTitle {{ font-size: {BODY_SIZE}px; font-weight: 600; }}
QLabel#debugOptionTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#updateDialogTitle {{ font-size: 20px; font-weight: 600; }}
QLabel#updateDialogVersion {{ font-size: {BODY_SIZE}px; font-weight: 500; }}
QLabel#aboutVersion, QLabel#shortcutKey {{ font-size: 18px; font-weight: 600; }}
QPushButton {{ font-size: {BODY_SIZE}px; font-weight: 500; }}
QPushButton#navButton {{ font-size: {BODY_SIZE}px; font-weight: 500; }}
QPushButton#navButton:checked {{ font-weight: 600; }}
QCheckBox {{ font-size: {BODY_SIZE}px; font-weight: 400; }}
QToolButton#detailsToggle, QToolTip {{ font-size: {SECONDARY_SIZE}px; font-weight: 400; }}
QTabBar::tab {{ font-size: {BODY_SIZE}px; font-weight: 400; }}
QTabBar::tab:selected {{ font-weight: 600; }}
QTextBrowser#releaseNotes {{ font-size: {BODY_SIZE}px; }}
QPlainTextEdit {{ font-family: 'Cascadia Mono', 'Consolas', 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: {SECONDARY_SIZE}px; }}
"""

FLOATING_TYPOGRAPHY_STYLE = f"""
QWidget {{ font-family: 'Segoe UI', 'Microsoft YaHei UI', 'Microsoft YaHei'; }}
QLabel#floatingTitle {{ font-size: {SECONDARY_SIZE}px; font-weight: 600; }}
QLabel#floatingHint {{ font-size: {CAPTION_SIZE}px; }}
QLabel#floatingState {{ font-size: {CAPTION_SIZE}px; font-weight: 500; }}
QPushButton {{ font-size: {SECONDARY_SIZE}px; font-weight: 500; }}
"""
