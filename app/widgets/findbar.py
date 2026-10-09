# -*- coding: utf-8 -*-
"""编辑器内嵌查找条（Ctrl+F）：在**当前这一篇**里找文字。

它和左侧栏的放大镜是两个入口、两件事，分工在设计稿 N-04 里说清楚过：

* Ctrl+F  = 在这篇里定位某个词（这里）
* 左栏放大镜 = 按文件名找笔记（见 sidebar.py）

之前用的是 QInputDialog 弹窗 —— 又丑又打断输入节奏，也不符合设计稿。
查找条内嵌在编辑区顶部，输入即跳到第一个命中，Enter 向下、Shift+Enter 向上、
Esc 关闭，是所有编辑器的通用习惯，不必教。

匹配计数在输入停顿 250ms 后才扫全篇：常见词在几百 KB 的笔记里能命中上千次，
每个按键都扫一遍纯属浪费，而停顿后再给数字用户根本察觉不到。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QTextCursor, QTextDocument, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton

from .. import icons, theme


def _label(text: str, color: str = theme.TEXT_MUTED, size: float = theme.FS_TINY,
           mono: bool = False) -> QLabel:
    lab = QLabel(text)
    family = theme.MONO_STACK if mono else theme.UI_STACK
    lab.setStyleSheet(f'color: {color}; font-size: {size}px; font-family: {family};')
    return lab


def _tool(icon_name: str, tip: str) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName('WinBtn')
    btn.setIcon(icons.icon(icon_name, theme.TEXT_SECOND, 13))
    btn.setIconSize(QSize(13, 13))
    btn.setFixedSize(24, 24)
    btn.setToolTip(tip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setAutoRaise(True)
    btn.setFocusPolicy(Qt.NoFocus)
    return btn


class FindBar(QFrame):
    """内嵌查找条。挂载时把编辑器实例交给它，查找动作直接作用于编辑器。"""

    close_requested = Signal()

    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('FindBar')
        self._editor = editor
        self._matches: list[int] = []       # 所有命中的绝对位置
        self._index = -1                    # 当前命中在 _matches 里的下标
        self.setFixedHeight(38)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(7)

        icon = QLabel()
        icon.setPixmap(icons.icon('find', theme.TEXT_MUTED, 13).pixmap(13, 13))
        lay.addWidget(icon)

        self._input = QLineEdit()
        self._input.setObjectName('FindInput')
        self._input.setPlaceholderText('在这篇里查找…')
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._on_query_changed)
        self._input.returnPressed.connect(self._find_next)
        self._input.installEventFilter(self)
        lay.addWidget(self._input, 1)

        self._count = _label('')
        self._count.setFixedWidth(64)
        self._count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._count)

        self._btn_prev = _tool('chevron-down', '上一个（Shift+Enter）')
        self._btn_prev.clicked.connect(self._find_prev)
        lay.addWidget(self._btn_prev)

        self._btn_next = _tool('chevron-right', '下一个（Enter）')
        self._btn_next.clicked.connect(self._find_next)
        lay.addWidget(self._btn_next)

        close = _tool('close', '关闭（Esc）')
        close.clicked.connect(self.close_requested)
        lay.addWidget(close)

        # 计数防抖：输入停顿后再扫全篇
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(250)
        self._scan_timer.timeout.connect(self._rescan)

        # Esc 只在输入框上有焦点时拦截，避免吞掉全局的 Esc 行为
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self._input)
        esc.setContext(Qt.WidgetShortcut)
        esc.activated.connect(self.close_requested)

    # ───────────────────────── 开关 ─────────────────────────

    def open(self) -> None:
        """展开并聚焦。编辑器里已选中的文字直接预填 —— 「查这个词」的最短路径。"""
        cursor = self._editor.textCursor()
        if cursor.hasSelection() and '\n' not in cursor.selectedText():
            self._input.setText(cursor.selectedText())
        self.show()
        self.raise_()
        self._input.setFocus()
        self._input.selectAll()

    # ───────────────────────── 查找逻辑 ─────────────────────────

    def _on_query_changed(self, _text: str) -> None:
        self._scan_timer.start()
        self._jump_to_first()

    def _jump_to_first(self) -> None:
        """输入即从当前光标向后跳到第一个命中；找不到就绕回开头再试一次。"""
        q = self._input.text()
        if not q:
            self._count.setText('')
            return
        flags = QTextDocument.FindFlags()
        if not self._editor.find(q, flags):
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            if not self._editor.find(q, flags):
                self._count.setText('无结果')
                self._count.setStyleSheet(
                    f'color: {theme.ERROR}; font-size: {theme.FS_TINY}px;'
                    f'font-family: {theme.UI_STACK};')

    def _rescan(self) -> None:
        """扫出所有命中位置，算出当前光标停在第几个。"""
        q = self._input.text()
        self._matches = []
        if not q:
            self._count.setText('')
            return
        doc: QTextDocument = self._editor.document()
        pos = 0
        flags = QTextDocument.FindFlags()
        while True:
            cur = doc.find(q, pos, flags)
            if cur.isNull():
                break
            self._matches.append(cur.selectionStart())
            pos = cur.selectionEnd()

        if not self._matches:
            self._index = -1
            self._count.setText('无结果')
            self._count.setStyleSheet(
                f'color: {theme.ERROR}; font-size: {theme.FS_TINY}px;'
                f'font-family: {theme.UI_STACK};')
            return
        here = self._editor.textCursor().selectionStart()
        self._index = 0
        for i, m in enumerate(self._matches):
            if m >= here:
                self._index = i
                break
        else:
            self._index = len(self._matches) - 1
        self._show_index()

    def _show_index(self) -> None:
        if not self._matches:
            return
        self._count.setText(f'{self._index + 1} / {len(self._matches)}')
        self._count.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FS_TINY}px;'
            f'font-family: {theme.MONO_STACK};')

    def _find_next(self) -> None:
        q = self._input.text()
        if not q:
            return
        if not self._editor.find(q, QTextDocument.FindFlags()):
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            self._editor.find(q, QTextDocument.FindFlags())
        self._rescan()

    def _find_prev(self) -> None:
        q = self._input.text()
        if not q:
            return
        flags = QTextDocument.FindFlag.FindBackward
        if not self._editor.find(q, flags):
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._editor.setTextCursor(cursor)
            self._editor.find(q, flags)
        self._rescan()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # QLineEdit 的 returnPressed 不区分修饰键，Shift+Enter 要自己拦
        if obj is self._input and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._find_prev() if event.modifiers() & Qt.ShiftModifier else self._find_next()
                return True
        return super().eventFilter(obj, event)
