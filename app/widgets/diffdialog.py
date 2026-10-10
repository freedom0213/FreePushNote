# -*- coding: utf-8 -*-
"""差异查看（右侧栏「查看差异」）。

回答的是一个问题：**这次推上去，仓库里到底会变成什么样？**

左版是仓库现在的内容（上一次推送的结果），右版是本地笔记此刻的样子 ——
两边都按推送时的同一套规则归一化过，所以这里看到的 +/− 就是推送的真实后果。

呈现上刻意做成等宽 + 逐行着色（+ 绿 / − 红 / 位置标记灰），而不是一句
「有 3 个文件改动了」。用户点这个按钮，就是想看清楚改了什么。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QSyntaxHighlighter,
                           QTextCharFormat)
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QToolButton, QVBoxLayout)

from .. import icons, theme

WIN_W = 840
WIN_H = 580


class _DiffPainter(QSyntaxHighlighter):
    """按行首字符给 diff 上色。

    用 highlighter 而不是把内容拼成 HTML：笔记的 diff 动辄几百上千行，
    拼 HTML 既慢又难复制；纯文本 + 着色两者都保住了。
    """

    def __init__(self, document) -> None:
        super().__init__(document)
        self._cache: dict[str, QTextCharFormat] = {}
        self._build()

    def _fmt(self, key: str, color: str, *, bold: bool = False,
             bg: str | None = None) -> None:
        f = QTextCharFormat()
        f.setForeground(QColor(color))
        if bold:
            f.setFontWeight(QFont.Bold)
        if bg:
            c = QColor(bg)
            c.setAlpha(26)
            f.setBackground(c)
        self._cache[key] = f

    def _build(self) -> None:
        self._fmt('file', theme.TEXT_STRONG, bold=True)
        self._fmt('hunk', theme.TEXT_WEAK)
        self._fmt('add', theme.SUCCESS, bg=theme.SUCCESS)
        self._fmt('del', theme.ERROR, bg=theme.ERROR)
        self._fmt('ctx', theme.TEXT_SECOND)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if not text:
            return
        if text.startswith('◆'):
            key = 'file'
        elif text.startswith('@@'):
            key = 'hunk'
        elif text.startswith('+++') or text.startswith('---'):
            key = 'hunk'
        elif text.startswith('+'):
            key = 'add'
        elif text.startswith('-'):
            key = 'del'
        else:
            key = 'ctx'
        self.setFormat(0, len(text), self._cache[key])


def compose(rows: list[dict]) -> str:
    """把逐文件的 diff 拼成一段可读的文本（文件之间空一行）。"""
    parts: list[str] = []
    for r in rows:
        parts.append(f"◆ {r.get('name', '')}    +{r.get('added', 0)} −{r.get('removed', 0)}")
        parts.append(str(r.get('text') or ''))
        parts.append('')
    return '\n'.join(parts).rstrip() + '\n'


class DiffDialog(QDialog):
    """差异查看窗口。``rows`` 来自 :func:`core.pipeline.diff_preview`。"""

    def __init__(self, rows: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._rows = rows
        self._drag_from = None
        self._build()

    def _build(self) -> None:
        total_add = sum(int(r.get('added', 0)) for r in self._rows)
        total_del = sum(int(r.get('removed', 0)) for r in self._rows)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName('DialogCard')
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── 标题栏 ──
        head = QFrame()
        head.setObjectName('DialogHeader')
        head.setFixedHeight(42)
        h = QHBoxLayout(head)
        h.setContentsMargins(16, 0, 10, 0)
        h.setSpacing(10)

        title = QLabel('查看差异')
        title.setStyleSheet(
            f'color: {theme.TEXT_STRONG}; font-size: 13.5px; font-weight: 600;')
        h.addWidget(title)

        sub = QLabel(f'本地内容 ↔ 仓库里的版本（上次推送的结果） · {len(self._rows)} 篇')
        sub.setStyleSheet(f'color: {theme.TEXT_WEAK}; font-size: {theme.FS_LABEL}px;')
        h.addWidget(sub)
        h.addStretch(1)

        stat = QLabel(f'+{total_add}  −{total_del}')
        stat.setStyleSheet(
            f'color: {theme.TEXT_SECOND}; font-size: {theme.FS_SMALL}px;'
            f'font-family: {theme.MONO_STACK};')
        h.addWidget(stat)

        copy = QToolButton()
        copy.setObjectName('LinkButton')
        copy.setText('复制')
        copy.setCursor(Qt.PointingHandCursor)
        copy.setToolTip('复制全部差异')
        copy.setFixedHeight(22)

        def do_copy() -> None:
            QGuiApplication.clipboard().setText(compose(self._rows))
            copy.setText('已复制')

        copy.clicked.connect(do_copy)
        h.addWidget(copy)

        close = QToolButton()
        close.setObjectName('WinBtn')
        close.setIcon(icons.icon('close', theme.TEXT_MUTED, 12))
        close.setIconSize(QSize(12, 12))
        close.setFixedSize(26, 26)
        close.setToolTip('关闭（Esc）')
        close.setCursor(Qt.PointingHandCursor)
        close.setAutoRaise(True)
        close.clicked.connect(self.reject)
        h.addWidget(close)
        lay.addWidget(head)

        # ── 差异正文 ──
        body = QFrame()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(14, 12, 14, 14)

        self._view = QPlainTextEdit()
        self._view.setObjectName('DiffView')
        self._view.setReadOnly(True)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont()
        font.setFamilies(['Sarasa Mono SC', 'Sarasa Gothic SC', 'Cascadia Mono',
                          'Consolas'])
        font.setPixelSize(12)
        self._view.setFont(font)
        self._view.setPlainText(compose(self._rows))
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._painter = _DiffPainter(self._view.document())
        body_lay.addWidget(self._view)
        lay.addWidget(body, 1)

        # 尺寸：跟随主窗口，但不小于可用高度
        parent_geo = self.parent().geometry() if self.parent() else None
        w = min(WIN_W, (parent_geo.width() - 60) if parent_geo else WIN_W)
        hh = min(WIN_H, (parent_geo.height() - 60) if parent_geo else WIN_H)
        self.setFixedSize(max(w, 520), max(hh, 380))

    # ───────────────────────── 交互 ─────────────────────────

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and event.position().y() <= 42:
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
