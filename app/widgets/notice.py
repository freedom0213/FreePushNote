# -*- coding: utf-8 -*-
"""统一的提示对话框 —— 替代 ``QMessageBox``。

为什么不用 ``QMessageBox``：它是 Windows 原生控件。圆角、字体、按钮形状、
图标全部来自系统，跟这套深色界面不是一回事 —— 夹在中间像从别的软件里
弹出来的东西。用户的评价很直接：「特别有终端风格」。

这里用自绘卡片重做。四类语义各有配色与图标，含义固定，不靠文字区分：

    info      蓝    一般告知（做完了一件事）
    success   绿    确实做成了
    warning  琥珀   需要留意，但没出错
    error     红    出错了；可带一段等宽细节（可选中、可一键复制）

两类用法：

    notice(self, '推送完成', '已推送 1 个文件。', kind='success')      # 告知
    if ask(self, '退出登录？', '…', ok_text='退出登录', danger=True):   # 确认
        …

**注意**：这个模块里所有对话框都走 ``NoticeDialog.exec()``。自测脚本靠
patch 这个方法来避免弹窗阻塞 —— 改动时别绕过它直接 ``show()``。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QToolButton,
                               QVBoxLayout)

from .. import icons, theme

#: 语义 → (图标名, 主色)
KINDS: dict[str, tuple[str, str]] = {
    'info': ('info-circle', theme.LINK),
    'success': ('check-circle', theme.SUCCESS),
    'warning': ('alert-circle', theme.WARNING),
    'error': ('alert-circle', theme.ERROR),
}

_BASE_W = 400
_DETAIL_W = 560


class NoticeDialog(QDialog):
    """深色卡片式提示框。无边框 + 自绘标题栏，与账户页 / 授权页同一套外壳。"""

    def __init__(self, parent=None, title: str = '', body: str = '', *,
                 kind: str = 'info', detail: str = '', ok_text: str = '知道了',
                 cancel_text: str | None = None, danger: bool = False) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._drag_from = None
        self.setFixedWidth(_DETAIL_W if detail else _BASE_W)
        self._build(title, body, kind, detail, ok_text, cancel_text, danger)

    # ───────────────────────── 构建 ─────────────────────────

    def _build(self, title, body, kind, detail, ok_text, cancel_text, danger) -> None:
        icon_name, color = KINDS.get(kind, KINDS['info'])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName('DialogCard')
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 16)
        lay.setSpacing(0)

        # ── 标题栏：图标 + 标题 + 关闭 ──
        head = QFrame()
        head.setObjectName('NoticeHeader')
        head.setFixedHeight(42)
        h = QHBoxLayout(head)
        h.setContentsMargins(16, 0, 8, 0)
        h.setSpacing(9)

        icon = QLabel()
        icon.setPixmap(icons.icon(icon_name, color, 16).pixmap(16, 16))
        h.addWidget(icon)

        title_label = QLabel(title)
        title_label.setObjectName('NoticeTitle')
        title_label.setStyleSheet(
            f'color: {theme.TEXT_STRONG}; font-size: 13.5px; font-weight: 600;')
        h.addWidget(title_label)
        h.addStretch(1)

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

        # ── 正文 ──
        inner = QVBoxLayout()
        inner.setContentsMargins(18, 14, 18, 0)
        inner.setSpacing(12)
        lay.addLayout(inner)

        if body:
            body_label = QLabel(body)
            body_label.setWordWrap(True)
            body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body_label.setStyleSheet(
                f'color: {theme.TEXT_BODY}; font-size: {theme.FS_SMALL}px;'
                f'line-height: 20px;')
            inner.addWidget(body_label)

        if detail:
            inner.addLayout(self._build_detail(detail))

        # ── 按钮行 ──
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        if cancel_text:
            cancel = QPushButton(cancel_text)
            cancel.setObjectName('DialogButton')
            cancel.setFixedHeight(32)
            cancel.setMinimumWidth(80)
            cancel.setCursor(Qt.PointingHandCursor)
            cancel.setDefault(False)
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel)
        ok = QPushButton(ok_text)
        ok.setObjectName('DangerButton' if danger else 'PrimaryButton')
        ok.setFixedHeight(32)
        ok.setMinimumWidth(88)
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        inner.addSpacing(2)
        inner.addLayout(row)

    def _build_detail(self, detail: str) -> QHBoxLayout:
        """技术细节块：等宽、可选中、带一键复制。

        失败原因、git 输出这类内容用户往往要贴到 issue 里，
        给个复制按钮比让他手动框选整段靠谱。
        """
        box = QPlainTextEdit()
        box.setObjectName('NoticeDetail')
        box.setPlainText(detail)
        box.setReadOnly(True)
        box.setFrameShape(QFrame.NoFrame)
        lines = detail.count('\n') + 1
        box.setFixedHeight(min(max(lines, 3), 9) * 17 + 16)

        copy = QToolButton()
        copy.setObjectName('LinkButton')
        copy.setText('复制')
        copy.setCursor(Qt.PointingHandCursor)
        copy.setToolTip('复制这段内容')
        copy.setFixedHeight(22)

        def do_copy() -> None:
            QGuiApplication.clipboard().setText(detail)
            copy.setText('已复制')

        copy.clicked.connect(do_copy)

        top = QHBoxLayout()
        top.setSpacing(6)
        hint = QLabel('详细信息')
        hint.setStyleSheet(f'color: {theme.TEXT_WEAK}; font-size: {theme.FS_LABEL}px;')
        top.addWidget(hint)
        top.addStretch(1)
        top.addWidget(copy)

        col = QVBoxLayout()
        col.setSpacing(5)
        col.addLayout(top)
        col.addWidget(box)

        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addLayout(col)
        return wrap

    # ───────────────────────── 拖动 ─────────────────────────

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


# ───────────────────────── 便捷入口 ─────────────────────────


def _center(parent, dlg: NoticeDialog) -> None:
    """无边框对话框不会自动居中，得自己算一次。"""
    if parent is None:
        return
    dlg.adjustSize()
    geo = parent.geometry()
    dlg.move(geo.x() + (geo.width() - dlg.width()) // 2,
             geo.y() + (geo.height() - dlg.height()) // 2)


def notice(parent, title: str, body: str = '', *, kind: str = 'info',
           detail: str = '', ok_text: str = '知道了') -> None:
    """告知类提示（单按钮）。替代 ``QMessageBox.information / warning``。"""
    dlg = NoticeDialog(parent, title, body, kind=kind, detail=detail, ok_text=ok_text)
    _center(parent, dlg)
    dlg.exec()


def ask(parent, title: str, body: str = '', *, kind: str = 'warning',
        detail: str = '', ok_text: str = '确定', cancel_text: str = '取消',
        danger: bool = False) -> bool:
    """确认类提示。返回 True 表示用户点了主按钮。替代 ``QMessageBox.question``。"""
    dlg = NoticeDialog(parent, title, body, kind=kind, detail=detail,
                       ok_text=ok_text, cancel_text=cancel_text, danger=danger)
    _center(parent, dlg)
    return dlg.exec() == QDialog.Accepted
