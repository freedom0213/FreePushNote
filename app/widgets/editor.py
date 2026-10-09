# -*- coding: utf-8 -*-
"""编辑区：QPlainTextEdit + **刻意弱化**的行号栏。

行号是这个项目里唯一被反复推翻的元素，实现前请先读这段历史：

* 早期版本做了「VS Code 式」的独立灰色行号条 + 满屏密排等宽文本，用户判定
  「太像 VS Code / 太终端」，要求**整个砍掉**（连开关都不要）。
* 2026-10-08 用户改主意：**要行号，但「数字要小点、不显眼」**。

所以这里的实现原则是「能看见，但不抢眼」：

===========  ============================  ==========================
维度          正文                          行号
===========  ============================  ==========================
字号          16 px（可 Ctrl+滚轮 调）        正文字号 − 4
颜色          #D4D4D4                       #454545（当前行 #6A6A6A）
背景          #1E1E1E                       与编辑区**同色**，不画独立灰条
===========  ============================  ==========================

「不画背景条」是关键：VS Code 的行号条之所以显眼，一半来自那条比编辑区更暗的
竖直色带，而不是数字本身。

另外两条约定：

1. **行号只标真实行** —— 也就是文件里确实存在换行符的那些行。窗口变窄导致长行
   被折断时，续行**不给行号**；否则拖动窗口宽度行号就会乱跳，状态栏的
   「共 N 行」也会跟它对不上。为了让「这是上一行的延续」一眼可辨，
   续行的行号位置会画一个极淡的小圆点。
2. 字号走 **Ctrl + 滚轮**，范围 12–32px。行高与行号字号按比例联动，
   放大之后不会挤成一团。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QFontMetricsF, QPainter,
                           QTextBlockFormat, QTextCursor)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .. import theme

# 等宽字体回退链：Sarasa 是等宽 CJK，中文与拉丁能对齐
MONO_FAMILIES = ['Sarasa Mono SC', 'Sarasa Gothic SC', 'Cascadia Mono', 'Consolas']


class _LineNumberArea(QWidget):
    """只负责占位与把绘制委托回编辑器（Qt 官方的经典做法）。"""

    def __init__(self, editor: 'CodeEditor') -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """纯文本编辑区。刻意保持记事本式的简洁：没有语法高亮、没有折叠、没有 minimap。"""

    font_size_changed = Signal(int)
    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('Editor')
        self.setFrameStyle(QPlainTextEdit.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setCursorWidth(2)

        self._font_size = theme.FS_BODY
        self._line_height = round(theme.FS_BODY * theme.LINE_HEIGHT_RATIO)
        self._base_font = QFont()
        self._gutter_font = QFont()
        # 重设行高要改文档格式，那会触发 textChanged —— 不能让「调字号」
        # 被当成「改了内容」，否则文件会平白变成「有改动待推送」。
        self._applying_format = False

        self._gutter = _LineNumberArea(self)

        self._apply_fonts()
        self.document().setDocumentMargin(theme.EDITOR_PAD_LEFT)

        self.blockCountChanged.connect(self._on_block_count_changed)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.textChanged.connect(self._on_text_changed)

        self._apply_line_height()
        self._refresh_gutter_width()

    # ───────────────────────── 对外接口 ─────────────────────────

    def load_text(self, text: str) -> None:
        """载入文本。``setPlainText`` 会把块格式重置掉，所以这里要补一次行高。"""
        self.setPlainText(text)
        self._apply_line_height()

    def line_col(self) -> tuple[int, int]:
        """当前光标的 (行, 列)，均从 1 开始 —— 状态栏直接显示这个。"""
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.positionInBlock() + 1

    def stats(self) -> tuple[int, int]:
        """(总行数, 字符数)。行数按块数算，末行没有换行也算一行。

        用 ``QTextDocument`` 自己维护的计数，**不要** ``toPlainText()`` 再数 ——
        那等于每次调用都把整篇复制一遍，10 万字的笔记上单次就要 0.4ms；
        而它会被光标移动、输入、刷新状态反复调用，累起来就是肉眼可见的滞涩。

        ``characterCount()`` 把每个段落分隔符也算 1 个字符，减掉块数正好得到
        「不含换行符的字符数」，与 Windows 记事本的口径一致（逐个用例核对过）。
        """
        return (max(1, self.blockCount()),
                max(0, self.document().characterCount() - self.blockCount()))

    def font_size(self) -> int:
        return self._font_size

    def set_font_size(self, size: int, emit: bool = True) -> None:
        """设置正文字号；会被夹在 FS_BODY_MIN ~ FS_BODY_MAX 之间。"""
        size = max(theme.FS_BODY_MIN, min(theme.FS_BODY_MAX, int(size)))
        if size == self._font_size:
            return
        self._font_size = size
        self._line_height = round(size * theme.LINE_HEIGHT_RATIO)
        self._apply_fonts()
        self._apply_line_height()
        self._refresh_gutter_width()
        self.viewport().update()
        self._gutter.update()
        if emit:
            self.font_size_changed.emit(size)

    # ───────────────────────── 字体 ─────────────────────────

    def _apply_fonts(self) -> None:
        """正文字体 + 行号字体一起刷新（行号字号永远比正文小 4）。"""
        base = QFont()
        base.setFamilies(MONO_FAMILIES)
        base.setPixelSize(self._font_size)
        base.setStyleStrategy(QFont.PreferAntialias)
        self._base_font = base
        self.setFont(base)

        gutter = QFont(base)
        gutter.setPixelSize(max(theme.GUTTER_FS_MIN,
                                min(theme.GUTTER_FS_MAX,
                                    self._font_size + theme.GUTTER_FS_DELTA)))
        self._gutter_font = gutter

        space = QFontMetricsF(base).horizontalAdvance(' ')
        self.setTabStopDistance(space * 4)

    # ───────────────────────── 行高 ─────────────────────────

    def _apply_line_height(self) -> None:
        """把全文档的块格式行高固定住。

        Qt 没有「行距」这种 API，只能通过块格式设置；而块格式不会自动作用于
        ``setPlainText`` 之后的新块，所以载入文本或改字号后都要重新刷一遍。
        """
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        # 2 == QTextBlockFormat::FixedHeight
        # （PySide6 的枚举不能直接 int()，而 setLineHeight 只收 int，所以写常量）
        fmt.setLineHeight(float(self._line_height), 2)
        self._applying_format = True
        try:
            cursor.mergeBlockFormat(fmt)
        finally:
            self._applying_format = False

    # ───────────────────────── 行号栏 ─────────────────────────

    def gutter_width(self) -> int:
        """行号区宽度：按当前最大行号的位数计算，避免行数变多时来回跳。"""
        digits = max(2, len(str(max(1, self.blockCount()))))
        metrics = QFontMetrics(self._gutter_font)
        return (theme.GUTTER_PAD_L
                + metrics.horizontalAdvance('9') * digits
                + theme.GUTTER_PAD_R)

    def _refresh_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def paint_gutter(self, event) -> None:
        painter = QPainter(self._gutter)
        # 与编辑区同色 —— 视觉上「没有这条带子」，只留下数字
        painter.fillRect(event.rect(), QColor(theme.BG_APP))
        painter.setFont(self._gutter_font)

        current_block = self.textCursor().blockNumber()
        right = self._gutter.width() - theme.GUTTER_PAD_R

        block = self.firstVisibleBlock()
        number = block.blockNumber()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        height = self.blockBoundingRect(block).height()
        bottom = top + height

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                color = (theme.GUTTER_FG_CURRENT if number == current_block
                         else theme.GUTTER_FG)
                painter.setPen(QColor(color))
                # 用块自身的实际高度做垂直居中，行号才会和正文那一行对齐
                painter.drawText(0, int(top), right, int(height),
                                 Qt.AlignRight | Qt.AlignVCenter, str(number + 1))
                self._paint_wrap_marks(painter, block, top)
            block = block.next()
            top = bottom
            height = self.blockBoundingRect(block).height()
            bottom = top + height
            number += 1

    def _paint_wrap_marks(self, painter: QPainter, block, top: float) -> None:
        """软换行的续行：在行号位置画一个极淡的小点。

        不画的话，续行那里就是一片空白 —— 用户会以为「怎么这行没有行号」，
        而实际上它根本不是新的一行。
        """
        layout = block.layout()
        if layout is None or layout.lineCount() <= 1:
            return
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.GUTTER_WRAP_MARK))
        x = self._gutter.width() - theme.GUTTER_PAD_R - 1.0
        for i in range(1, layout.lineCount()):
            line = layout.lineAt(i)
            y = top + line.y() + line.height() / 2.0
            painter.drawEllipse(QPointF(x, y), 1.6, 1.6)
        painter.restore()

    # ───────────────────────── 信号响应 ─────────────────────────

    def _on_block_count_changed(self, _count: int) -> None:
        self._refresh_gutter_width()

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._refresh_gutter_width()

    def _on_cursor_position_changed(self) -> None:
        self._gutter.update()

    def _on_text_changed(self) -> None:
        """转发成 ``content_changed``：只有真正的文本编辑才算「内容变了」。

        直接连 ``textChanged`` 会把「重设行高」也当成内容修改，
        文件会平白变成「有改动待推送」。
        """
        if not self._applying_format:
            self.content_changed.emit()

    # ───────────────────────── 事件 ─────────────────────────

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Ctrl + 滚轮 = 缩放字号。这是编辑器里的通用手势，不用教。"""
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.set_font_size(self._font_size + (1 if delta > 0 else -1))
                event.accept()
                return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QRect(cr.left(), cr.top(), self.gutter_width(), cr.height())
        )
