# -*- coding: utf-8 -*-
"""工具栏（38px）：新建 / 打开 / 保存 ｜ 查找 …… 设置。

注意：**Push 主按钮不在这里**。早期版本把它放在工具栏最右侧，v3 改掉了——
用户的要求是「推送相关的信息（仓库、状态、按钮、历史）统一收进右侧栏」。

按钮统一「图标 + 文字」，因为纯图标对不熟悉的人不够自解释；
但光标移上去仍是手型（``PointingHandCursor``），符合桌面软件习惯。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QToolButton)

from .. import icons, theme


class _ToolButton(QToolButton):
    def __init__(self, icon_name: str, text: str, tip: str,
                 color: str = '#9D9D9D', icon_size: int = 14, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('ToolBtn')
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIcon(icons.icon(icon_name, color, icon_size))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setText(text)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoRaise(True)
        self.setFixedHeight(28)


class EditorToolBar(QFrame):
    """顶部第二行。所有动作都通过信号抛给主窗口，控件本身不做事。"""

    new_requested = Signal()
    open_requested = Signal()
    save_requested = Signal()
    find_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('ToolBar')
        self.setFixedHeight(theme.TOOLBAR_H)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(6)

        self.btn_new = _ToolButton('new', '新建', '新建一个 txt（Ctrl+N）')
        self.btn_new.clicked.connect(self.new_requested)
        row.addWidget(self.btn_new)

        self.btn_open = _ToolButton('open', '打开', '打开一个 txt（Ctrl+O）')
        self.btn_open.clicked.connect(self.open_requested)
        row.addWidget(self.btn_open)

        self.btn_save = _ToolButton('save', '保存', '保存到磁盘（Ctrl+S）')
        self.btn_save.clicked.connect(self.save_requested)
        row.addWidget(self.btn_save)

        divider = QFrame()
        divider.setFixedSize(1, 16)
        divider.setStyleSheet(f'background: {theme.BORDER_STRONG};')
        row.addSpacing(2)
        row.addWidget(divider)
        row.addSpacing(2)

        self.btn_find = _ToolButton('find', '查找', '在当前文件中查找（Ctrl+F）')
        self.btn_find.clicked.connect(self.find_requested)
        row.addWidget(self.btn_find)

        row.addStretch(1)

        self.btn_settings = _ToolButton('settings', '设置', '设置（Ctrl+,）',
                                        icon_size=16)
        self.btn_settings.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.clicked.connect(self.settings_requested)
        row.addWidget(self.btn_settings)

        self.set_has_file(False)

    def set_has_file(self, has_file: bool) -> None:
        """没有打开文件时，保存 / 查找 应当是禁用的 —— 别让用户点了没反应。"""
        self.btn_save.setEnabled(has_file)
        self.btn_find.setEnabled(has_file)
