"""页面共用的表单构建与下拉项选择辅助"""
from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QSpinBox, QVBoxLayout, QWidget
from fishing_assistant.desktop.widgets import ScrollSafeDoubleSpinBox, ScrollSafeSpinBox
from fishing_assistant.desktop.design import ui_font


class FormHelpersMixin:
    """页面共用的表单构建与下拉项选择辅助；由 MainWindow 组装，不单独实例化。"""

    @staticmethod
    def _card_heading(title: str, hint: str = "") -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setToolTip(hint)
        title_label.setAccessibleDescription(hint)
        layout.addWidget(title_label)
        return layout

    @staticmethod
    def _form_label(title: str, hint: str = "") -> QWidget:
        widget = QWidget()
        widget.setToolTip(hint)
        widget.setAccessibleName(title)
        widget.setAccessibleDescription(hint)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("formLabel")
        title_label.setToolTip(hint)
        title_label.setAccessibleDescription(hint)
        layout.addWidget(title_label)
        return widget

    @staticmethod
    def _spin_box(minimum: int, maximum: int, value: int, suffix: str) -> QSpinBox:
        spin = ScrollSafeSpinBox()
        # 固定使用西文数字，避免部分 Windows 区域设置把数值渲染成异常字形。
        spin.setLocale(QLocale.c())
        spin.setGroupSeparatorShown(False)
        font = ui_font()
        spin.setFont(font)
        if spin.lineEdit() is not None:
            spin.lineEdit().setFont(font)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _double_spin_box(
        minimum: float,
        maximum: float,
        value: float,
        suffix: str,
    ) -> QDoubleSpinBox:
        spin = ScrollSafeDoubleSpinBox()
        spin.setLocale(QLocale.c())
        spin.setGroupSeparatorShown(False)
        spin.setDecimals(1)
        spin.setSingleStep(0.1)
        font = ui_font()
        spin.setFont(font)
        if spin.lineEdit() is not None:
            spin.lineEdit().setFont(font)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _select_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index < 0:
            combo.addItem(value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    @staticmethod
    def _mode_name(value: str) -> str:
        return {"borderless": "无边框全屏", "fullscreen": "独占全屏", "windowed": "窗口模式"}.get(value, value)
