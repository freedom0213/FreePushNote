# -*- coding: utf-8 -*-
"""对话框的统一外壳：圆角卡片 + 阴影 + 可拖动 + 统一头部与底部。

主窗口是固定深色且无边框的。如果对话框走系统标题栏，暗色界面上会横着一条
亮色标题栏 —— 一眼就看出是「两个软件拼起来的」。所以几个对话框共用这套外壳。

用法::

    class MyDialog(FramedDialog):
        def __init__(self, parent=None):
            super().__init__('标题', parent, icon_name='folder')
            self.set_subtitle('步骤 1 / 2 · 选择文件')
            self.body.addWidget(label('说明文字', wrap=True))
            self.add_ghost('取消').clicked.connect(self.reject)
            self.add_primary('下一步', 'chevron-right').clicked.connect(self._next)
            self.finish()      # 自适应大小 + 在主窗口居中
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QPushButton, QToolButton,
                               QVBoxLayout)

from .. import icons, theme


def label(text: str = '', color: str = theme.TEXT_MUTED, size: float = theme.FS_SMALL,
          weight: int = 400, mono: bool = False, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    family = theme.MONO_STACK if mono else theme.UI_STACK
    lab.setStyleSheet(f'color: {color}; font-size: {size}px; font-weight: {weight};'
                      f'font-family: {family};')
    lab.setWordWrap(wrap)
    return lab


def divider() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f'background: {theme.BORDER};')
    return f


def note_box(text: str, kind: str = 'warn', icon_name: str | None = None) -> QFrame:
    """提示条：左侧图标 + 自动换行的说明。``kind`` = ``warn`` | ``info``。"""
    box = QFrame()
    box.setObjectName('NoteWarn' if kind == 'warn' else 'NoteInfo')
    lay = QHBoxLayout(box)
    lay.setContentsMargins(11, 10, 11, 10)
    lay.setSpacing(9)

    warn = kind == 'warn'
    color = theme.WARNING if warn else theme.TEXT_SECOND
    ico = QLabel()
    ico.setPixmap(icons.icon(icon_name or ('alert-circle' if warn else 'link'),
                             color, 14).pixmap(14, 14))
    ico.setFixedSize(14, 14)
    lay.addWidget(ico, 0, Qt.AlignTop)

    body = label(text, theme.WARNING if warn else theme.TEXT_BODY,
                 theme.FS_TINY, wrap=True)
    lay.addWidget(body, 1)
    return box


class FramedDialog(QDialog):
    """无边框深色对话框的统一外壳。子类往 ``self.body`` 里塞内容即可。"""

    def __init__(self, title: str, parent=None, *, icon_name: str = 'file',
                 width: int = 470, icon_color: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._drag_from = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)      # 留给阴影

        self.card = QFrame()
        self.card.setObjectName('DialogCard')
        self.card.setFixedWidth(width)
        outer.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(44)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        col = QVBoxLayout(self.card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(self._build_header(title, icon_name, icon_color))

        self._subtitle = label('', theme.TEXT_WEAK, theme.FS_LABEL)
        self._subtitle.setContentsMargins(20, 10, 20, 0)
        self._subtitle.setVisible(False)
        col.addWidget(self._subtitle)

        body = QFrame()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(20, 18, 20, 0)
        self.body.setSpacing(12)
        col.addWidget(body)

        foot = QFrame()
        self.footer = QHBoxLayout(foot)
        self.footer.setContentsMargins(20, 16, 20, 18)
        self.footer.setSpacing(10)
        self.footer.addStretch(1)
        col.addWidget(foot)

    def _build_header(self, title: str, icon_name: str,
                      icon_color: str | None) -> QFrame:
        head = QFrame()
        head.setObjectName('DialogHeader')
        head.setFixedHeight(52)
        h = QHBoxLayout(head)
        h.setContentsMargins(20, 0, 14, 0)
        h.setSpacing(9)

        ico = QLabel()
        ico.setPixmap(icons.icon(icon_name, icon_color or theme.TEXT_BODY,
                                 16).pixmap(16, 16))
        ico.setFixedSize(16, 16)
        h.addWidget(ico)

        self._title = QLabel(title)
        self._title.setStyleSheet(
            f'color: {theme.TEXT_STRONG}; font-size: 14px; font-weight: 600;')
        h.addWidget(self._title)
        h.addStretch(1)
        self.header = h

        close = QToolButton()
        close.setObjectName('WinBtn')
        close.setIcon(icons.icon('close', theme.TEXT_MUTED, 12))
        close.setIconSize(QSize(12, 12))
        close.setFixedSize(26, 26)
        close.setCursor(Qt.PointingHandCursor)
        close.setAutoRaise(True)
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        h.addWidget(close)
        return head

    # ───────────────────────── 对外接口 ─────────────────────────

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def add_primary(self, text: str, icon_name: str | None = None) -> QPushButton:
        btn = QPushButton(('  ' + text) if icon_name else text)
        btn.setObjectName('PrimaryButton')
        btn.setFixedHeight(34)
        if icon_name:
            btn.setIcon(icons.icon(icon_name, '#FFFFFF', 13))
            btn.setIconSize(QSize(13, 13))
        btn.setCursor(Qt.PointingHandCursor)
        self.footer.addWidget(btn)
        return btn

    def add_ghost(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName('DialogButton')
        btn.setFixedHeight(34)
        btn.setMinimumWidth(74)
        btn.setCursor(Qt.PointingHandCursor)
        self.footer.addWidget(btn)
        return btn

    def finish(self) -> None:
        """自适应大小并在主窗口里居中。"""
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            win = parent.window()
            geo = win.frameGeometry() if win is not None else parent.geometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

    # 无边框窗口：按住空白处可以拖动
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_from = (event.globalPosition().toPoint()
                               - self.frameGeometry().topLeft())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(event)


class CheckButton(QToolButton):
    """自绘复选框。

    不用 ``QCheckBox`` 的原因：它的原生 indicator 由平台样式绘制，
    在我们这套固定深色主题下会渲染成一个亮色方块，和整体对不上。
    这里用 SVG 画一个（勾选 = 主色填充 + 白色对勾），与设计稿一致。
    """

    def __init__(self, checked: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('WinBtn')
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self._checked = checked
        self.clicked.connect(self.toggle)
        self._sync()

    def isChecked(self) -> bool:  # noqa: N802 - 与 Qt 命名保持一致
        return self._checked

    def setChecked(self, value: bool) -> None:  # noqa: N802
        if self._checked != value:
            self._checked = value
            self._sync()

    def toggle(self) -> None:
        self._checked = not self._checked
        self._sync()

    def _sync(self) -> None:
        if self._checked:
            self.setIcon(icons.icon('checkbox-on', theme.PRIMARY, 15,
                                    second='#FFFFFF'))
        else:
            self.setIcon(icons.icon('checkbox-off', theme.TEXT_WEAK, 15))
        self.setIconSize(QSize(15, 15))
