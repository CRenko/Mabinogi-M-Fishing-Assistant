"""食物制作的只读预留页面，不连接引擎。"""
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from fishing_assistant.desktop.widgets import Card


class FoodCraftingPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageCanvas")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 10, 0)
        card = Card()
        content = QVBoxLayout(card)
        content.setContentsMargins(24, 22, 24, 24)
        content.setSpacing(12)
        for text, role in (
            ("食物制作", "cardTitle"),
            ("本版本暂未开放", "availabilityBadge"),
        ):
            label = QLabel(text)
            label.setObjectName(role)
            label.setWordWrap(True)
            content.addWidget(label)
        layout.addWidget(card)
        layout.addStretch(1)
