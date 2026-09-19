"""固定页内导航和独立滚动区；只管理布局，不持有业务配置。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from fishing_assistant.desktop.widgets import ScrollSafeTabBar


class SectionedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sectionedPage")
        self._keys = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.tabs = ScrollSafeTabBar()
        self.tabs.setObjectName("sectionTabs")
        self.tabs.setAccessibleName("页面分类")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        layout.addWidget(self.tabs)
        self.sections = QStackedWidget()
        layout.addWidget(self.sections, 1)
        self.tabs.currentChanged.connect(self.sections.setCurrentIndex)

    def add_section(self, key: str, title: str) -> QVBoxLayout:
        if key in self._keys:
            raise ValueError(f"重复页面分类：{key}")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        canvas = QWidget()
        canvas.setObjectName("pageCanvas")
        body = QVBoxLayout(canvas)
        body.setContentsMargins(0, 0, 9, 0)
        body.setSpacing(12)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(canvas)
        self._keys.append(key)
        self.sections.addWidget(scroll)
        self.tabs.addTab(title)
        return body

    def select_section(self, key: str) -> None:
        self.tabs.setCurrentIndex(self._keys.index(key))

    def current_scroll(self) -> QScrollArea:
        return self.sections.currentWidget()

    # 保留页面检查/预览的滚动接口，各分类独立保存滚动位置。
    def widget(self) -> QWidget:
        return self.current_scroll().widget()

    def verticalScrollBar(self):
        return self.current_scroll().verticalScrollBar()
