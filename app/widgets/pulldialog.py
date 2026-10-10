# -*- coding: utf-8 -*-
"""拉取确认层：**先看清楚会动哪些笔记，再动手**。

和推送的确认层（S-01）是同一个哲学 —— 写用户文件之前，把真实清单摆出来。
这里摆的是三组，含义各不相同，所以必须分开显示，不能混成一句「有 4 处变化」：

    将更新      本地没改过 → 直接用远端版本覆盖（内容可以从 git 历史找回）
    将自动合并  两边改的位置不重叠 → 合并结果里两边的改动都在
    有冲突      两边改到同一处 → **保留你的版本**，远端那份不写进来

界面上还要说清备份：改写前会先复制一份到 ``~/.pushnote/backups``。
用户最怕的是「点了什么，我的笔记就变了」，把保险措施写在按钮旁边，
比事后解释有用。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QToolButton, QVBoxLayout)

from core import config, pipeline

from .. import icons, theme

CARD_W = 540


def _label(text: str, color: str = theme.TEXT_MUTED, size: float = theme.FS_SMALL,
           weight: int = 400, mono: bool = False) -> QLabel:
    lab = QLabel(text)
    family = theme.MONO_STACK if mono else theme.UI_STACK
    lab.setStyleSheet(
        f'color: {color}; font-size: {size}px; font-weight: {weight};'
        f'font-family: {family};')
    lab.setWordWrap(True)
    return lab


class PullDialog(QDialog):
    """展示拉取计划并确认。``exec() == Accepted`` 表示用户点了「开始拉取」。"""

    def __init__(self, plan: pipeline.PullPlan, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._plan = plan
        self._drag_from = None
        self.setFixedWidth(CARD_W)
        self._build()

    def _build(self) -> None:
        plan = self._plan

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName('DialogCard')
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 16)
        lay.setSpacing(0)

        # ── 标题栏 ──
        head = QFrame()
        head.setObjectName('DialogHeader')
        head.setFixedHeight(42)
        h = QHBoxLayout(head)
        h.setContentsMargins(16, 0, 10, 0)
        h.setSpacing(9)

        icon = QLabel()
        icon.setPixmap(icons.icon('pull', theme.PRIMARY_HOVER, 16).pixmap(16, 16))
        h.addWidget(icon)
        title = QLabel('拉取远端更新')
        title.setStyleSheet(
            f'color: {theme.TEXT_STRONG}; font-size: 13.5px; font-weight: 600;')
        h.addWidget(title)
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

        inner = QVBoxLayout()
        inner.setContentsMargins(18, 14, 18, 0)
        inner.setSpacing(11)
        lay.addLayout(inner)

        inner.addWidget(_label(
            f'远端有 {plan.behind} 个提交是本地没有的。下面是这些提交会带来什么影响：',
            theme.TEXT_BODY, theme.FS_SMALL))

        groups = [
            ('将更新', plan.updated, theme.PRIMARY_HOVER,
             '本地没改过，直接用远端版本覆盖'),
            ('将自动合并', plan.merged, theme.SUCCESS,
             '两边改的位置不重叠，合并后两边的内容都在'),
            ('有冲突', plan.conflicts, theme.ERROR,
             '两边改到了同一处 —— 会保留你的版本，远端那份不写进来'),
        ]
        shown = [g for g in groups if g[1]]
        if not shown:
            inner.addWidget(_label('没有需要写回本地的改动。',
                                   theme.TEXT_SECOND, theme.FS_SMALL))
        for title_text, items, color, hint in shown:
            inner.addWidget(self._build_group(title_text, items, color, hint))

        # 远端改了、但不打算同步的东西（自动生成的站点文件）。
        # 不说清楚，用户会以为「Pull 成功了，网页上的修改应该生效了」。
        if plan.outside:
            inner.addWidget(self._build_outside(plan.outside))

        # ── 备份说明 ──
        note = QFrame()
        note.setObjectName('NoteInfo')
        n_lay = QVBoxLayout(note)
        n_lay.setContentsMargins(12, 10, 12, 10)
        n_lay.setSpacing(4)
        n_lay.addWidget(_label('动手之前会先备份', theme.TEXT_BODY,
                               theme.FS_TINY, 600))
        n_lay.addWidget(_label(
            f'被改写的笔记会先复制一份到 {config.BACKUPS_DIR}，'
            '只保留最近 5 次。备份失败就不会动你的文件。',
            theme.TEXT_SECOND, theme.FS_TINY))
        inner.addWidget(note)

        # ── 按钮 ──
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        cancel = QPushButton('取消')
        cancel.setObjectName('DialogButton')
        cancel.setFixedHeight(32)
        cancel.setMinimumWidth(80)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton('开始拉取')
        ok.setObjectName('PrimaryButton')
        ok.setFixedHeight(32)
        ok.setMinimumWidth(96)
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        inner.addSpacing(2)
        inner.addLayout(row)

    def _build_group(self, title: str, items: list, color: str,
                     hint: str) -> QFrame:
        box = QFrame()
        box.setObjectName('AuthStep')
        b_lay = QVBoxLayout(box)
        b_lay.setContentsMargins(12, 10, 12, 10)
        b_lay.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(7)
        dot = QFrame()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f'background: {color}; border-radius: 3px;')
        head.addWidget(dot)
        head.addWidget(_label(f'{title}（{len(items)} 篇）', color, theme.FS_TINY, 600))
        head.addStretch(1)
        b_lay.addLayout(head)
        b_lay.addWidget(_label(hint, theme.TEXT_FAINT, theme.FS_LABEL))

        for f in items:
            # 只列文件名 —— 说明写在组头（每组一句），逐行再重复一遍既冗余，
            # 又会在窄卡片里折行，把清单挤得很难读。单篇的额外说明走 tooltip。
            name = _label(f.name, theme.TEXT_BODY, theme.FS_SMALL, mono=True)
            if f.note:
                name.setToolTip(f.note)
            row = QHBoxLayout()
            row.setSpacing(7)
            row.addWidget(name)
            row.addStretch(1)
            b_lay.addLayout(row)
        return box

    def _build_outside(self, paths: list[str]) -> QFrame:
        """远端改了、但不会被同步的路径（自动生成的站点文件）。"""
        box = QFrame()
        box.setObjectName('NoteWarn')
        b_lay = QVBoxLayout(box)
        b_lay.setContentsMargins(12, 10, 12, 10)
        b_lay.setSpacing(4)
        b_lay.addWidget(_label(f'不会同步（{len(paths)} 个自动生成的文件）',
                               theme.WARNING, theme.FS_TINY, 600))
        b_lay.addWidget(_label(
            '这些文件由笔记原文生成，每次推送都会重新生成；'
            '在网页上直接改它们，下次推送会被覆盖。',
            theme.TEXT_SECOND, theme.FS_LABEL))
        for p in paths[:6]:
            b_lay.addWidget(_label(f'· {p}', theme.TEXT_FAINT, theme.FS_LABEL,
                                   mono=True))
        if len(paths) > 6:
            b_lay.addWidget(_label(f'· 等共 {len(paths)} 个', theme.TEXT_FAINT,
                                   theme.FS_LABEL))
        return box

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
