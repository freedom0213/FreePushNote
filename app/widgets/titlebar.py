# -*- coding: utf-8 -*-
"""自定义标题栏（34px）。

只有自绘标题栏才能同时拿到「窗口圆角 11px」和「深色一体化」。窗口用
``Qt.FramelessWindowHint`` 去掉系统边框，拖动交给 ``startSystemMove()``
（比手算坐标稳，且能吃到 Windows 的贴边 / 磁吸行为）。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QToolButton)

from .. import icons, theme


class _WinButton(QToolButton):
    """标题栏右侧的 最小化 / 最大化 / 关闭。"""

    def __init__(self, icon_name: str, tip: str, hover: str = '', parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('WinBtn')
        if hover:
            self.setProperty('hoverRole', hover)
        self.setFixedSize(44, theme.TITLEBAR_H)
        self.setIconSize(QSize(12, 12))
        self.setIcon(icons.icon(icon_name, '#B4B4B4', 12))
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoRaise(True)


class TitleBar(QFrame):
    """顶部 34px：应用名 + 当前文件名 + 窗口控制。"""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName('TitleBar')
        self.setFixedHeight(theme.TITLEBAR_H)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 0, 0)
        row.setSpacing(0)

        # ── 左：图标 + 应用名 + 分隔线 + 文件名 ──
        left = QHBoxLayout()
        left.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(icons.icon('app', '#9D9D9D', 16, second=theme.PRIMARY).pixmap(16, 16))
        logo.setFixedSize(16, 16)
        left.addWidget(logo)

        app_name = QLabel('FreePushNote')
        app_name.setObjectName('AppName')
        left.addWidget(app_name)

        divider = QFrame()
        divider.setFixedSize(1, 12)
        divider.setStyleSheet(f'background: {theme.BORDER_STRONG};')
        left.addWidget(divider)

        self._file_label = QLabel('未打开任何文件')
        self._file_label.setObjectName('TitleFileName')
        left.addWidget(self._file_label)

        left.addStretch(1)
        row.addLayout(left)

        # ── 右：窗口控制 ──
        self._btn_min = _WinButton('min', '最小化')
        self._btn_min.clicked.connect(window.showMinimized)

        self._btn_max = _WinButton('max', '最大化')
        self._btn_max.clicked.connect(window.toggle_maximize)

        self._btn_close = _WinButton('close', '关闭', hover='close')
        self._btn_close.clicked.connect(window.close)

        for b in (self._btn_min, self._btn_max, self._btn_close):
            row.addWidget(b)

    # ───────────────────────── 对外接口 ─────────────────────────

    def set_file_name(self, name: str | None, dirty: bool = False) -> None:
        """更新标题里的文件名；``dirty`` 为真时前面加一个圆点表示未保存。"""
        if not name:
            self._file_label.setText('未打开任何文件')
            self._file_label.setStyleSheet(f'color: {theme.TEXT_WEAK};')
            return
        self._file_label.setStyleSheet(f'color: {theme.TEXT_PRIMARY};')
        self._file_label.setText(f'● {name}' if dirty else name)

    def set_maximized(self, maximized: bool) -> None:
        self._btn_max.setIcon(icons.icon('restore' if maximized else 'max', '#B4B4B4', 12))
        self._btn_max.setToolTip('还原' if maximized else '最大化')

    # ───────────────────────── 拖动 / 双击 ─────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._window.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
