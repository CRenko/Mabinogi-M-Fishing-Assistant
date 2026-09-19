"""兼容导入入口。新界面实现位于 desktop/，请勿在此新增页面逻辑。"""

from fishing_assistant import window_target
from fishing_assistant.desktop.dialogs import (
    InventoryCleanupTestDialog,
    InventoryCleanupWarningDialog,
    UpdateAvailableDialog,
    WOnlyModeWarningDialog,
)
from fishing_assistant.desktop.floating_status import FloatingStatusBar
from fishing_assistant.desktop.main_window import MainWindow
from fishing_assistant.desktop.styles import (
    DAY_STYLE,
    FLOATING_DAY_STYLE,
    FLOATING_NIGHT_STYLE,
    NIGHT_STYLE,
)
from fishing_assistant.desktop.widgets import (
    Card,
    MetricCard,
    ScrollSafeComboBox,
    ScrollSafeDoubleSpinBox,
    ScrollSafeSlider,
    ScrollSafeSpinBox,
)

__all__ = [
    "Card",
    "DAY_STYLE",
    "FLOATING_DAY_STYLE",
    "FLOATING_NIGHT_STYLE",
    "FloatingStatusBar",
    "InventoryCleanupTestDialog",
    "InventoryCleanupWarningDialog",
    "MainWindow",
    "MetricCard",
    "NIGHT_STYLE",
    "ScrollSafeComboBox",
    "ScrollSafeDoubleSpinBox",
    "ScrollSafeSlider",
    "ScrollSafeSpinBox",
    "UpdateAvailableDialog",
    "WOnlyModeWarningDialog",
    "window_target",
]
