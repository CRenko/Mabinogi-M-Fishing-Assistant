"""自动制作子菜单；保留材料加工，食物制作仅展示预留说明。"""
from PySide6.QtWidgets import QTabWidget
from fishing_assistant.desktop.widgets import ScrollSafeTabBar
from fishing_assistant.features.food.page import FoodCraftingPage


class CraftingHubPage(QTabWidget):
    def __init__(self, material_page, parent=None):
        super().__init__(parent)
        self.setObjectName("craftingHub")
        self.setTabBar(ScrollSafeTabBar())
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)
        self.addTab(material_page, "材料加工（测试）")
        self.food_page = FoodCraftingPage()
        self.addTab(self.food_page, "食物制作 · 准备中")
        self.setTabToolTip(1, "后续版本开放；当前仅预留入口，不执行制作。")
