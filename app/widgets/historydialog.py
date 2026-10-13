# -*- coding: utf-8 -*-
"""提交历史（右栏「最近推送 → 全部记录」）。

回答的是另一个问题：**这台机器（或这个仓库）到底推过什么，每次改了什么？**

与「查看差异」的分工要分清：

* **查看差异** = 本地此刻的样子 ↔ 上次推上去的样子 —— 「我这次推上去会改什么」
* **提交历史** = 按时间轴列出每一次提交，逐次看它改了什么 —— 「过去都发生了什么」

两栏布局：左边提交列表（时间 / 提交信息 / 短 sha），右边选中那一次的逐行 diff。
顶部可切「本机已推」与「远端仓库」—— **后者才有别人在另一台电脑或网页上推的提交**，
需要联网读，所以由主窗口去后台取，这里只负责显示。

渲染复用「查看差异」那套（同一个高亮器），保证两处的绿 + / 红 − 长得一样。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from .. import theme
from .dialogbase import FramedDialog, label
from .diffdialog import _DiffPainter      # 同一套着色，两处观感必须一致

WIN_W = 920
LIST_W = 262
PANES_H = 356


def _count_patch(text: str) -> tuple[int, int, int]:
    """从统一格式的补丁里数出 ``(文件数, 新增行, 删除行)``。

    只认行首：``+++`` / ``---`` 是文件头，不能算进增删。
    """
    files = added = removed = 0
    for line in text.splitlines():
        if line.startswith('+++ ') or line.startswith('--- '):
            if line.startswith('+++ '):
                files += 1
            continue
        if line.startswith('+'):
            added += 1
        elif line.startswith('-'):
            removed += 1
    return files, added, removed


class _ScopeButton(QToolButton):
    """顶部的「本机已推 / 远端仓库」切换。选中态自己维护（QSS 的 :checked 不便调）。"""

    def __init__(self, text: str, tip: str, parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(26)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                f'QToolButton {{ color: {theme.TEXT_STRONG}; font-size: {theme.FS_SMALL}px;'
                f' font-weight: 600; background: {theme.alpha(theme.PRIMARY, 0.18)};'
                f' border: 1px solid {theme.alpha(theme.PRIMARY, 0.55)};'
                f' border-radius: 6px; padding: 0 11px; }}')
        else:
            self.setStyleSheet(
                f'QToolButton {{ color: {theme.TEXT_MUTED}; font-size: {theme.FS_SMALL}px;'
                f' background: transparent; border: 1px solid transparent;'
                f' border-radius: 6px; padding: 0 11px; }}'
                f'QToolButton:hover {{ color: {theme.TEXT_BODY}; }}')


class _CommitRow(QFrame):
    """一行提交：提交信息 + 时间，下面一行短 sha + 作者。整行可点。"""

    clicked = Signal(str)

    def __init__(self, commit: dict, parent=None) -> None:
        super().__init__(parent)
        self.sha = str(commit.get('sha') or '')
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(9, 5, 9, 5)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._msg = label(str(commit.get('message') or '（无提交信息）'),
                          theme.TEXT_BODY, theme.FS_SMALL)
        top.addWidget(self._msg, 1)
        self._when = label(str(commit.get('when') or ''), theme.TEXT_FAINT,
                           theme.FS_TINY, mono=True)
        top.addWidget(self._when)
        lay.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._sha = label(str(commit.get('short') or ''), theme.TEXT_FAINT,
                          theme.FS_TINY, mono=True)
        bottom.addWidget(self._sha)
        bottom.addWidget(label(str(commit.get('author') or ''), theme.TEXT_FAINT,
                               theme.FS_TINY))
        bottom.addStretch(1)
        lay.addLayout(bottom)

        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        if on:
            bg = theme.alpha(theme.PRIMARY, 0.20)
            border = theme.alpha(theme.PRIMARY, 0.55)
        else:
            bg = 'transparent'
            border = 'transparent'
        self.setStyleSheet(
            f'QFrame {{ background: {bg}; border: 1px solid {border};'
            f' border-radius: 6px; }}')

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.sha:
            self.clicked.emit(self.sha)
        super().mousePressEvent(event)


class HistoryDialog(FramedDialog):
    """两栏的提交历史。数据由主窗口取好再喂进来（联网的事不放在窗口里）。"""

    #: 用户选中某次提交，要看它的 diff
    commit_selected = Signal(str)
    #: 用户切到「远端仓库」，但远端数据还没有 —— 主窗口去后台 fetch
    remote_requested = Signal()

    def __init__(self, group: dict, parent=None) -> None:
        super().__init__('提交历史', parent, icon_name='history', width=WIN_W)
        self._group = group
        self._rows: dict[str, _CommitRow] = {}
        self._cache: dict[str, dict] = {}      # 'local' / 'remote' → 取回的结果
        self._scope = 'local'
        self._current_sha = ''
        self._remote_pending = False       # 已经请主窗口去取了，别重复发请求
        self._build()
        card_w = WIN_W
        if parent is not None:
            card_w = max(640, min(WIN_W, parent.width() - 80))
        self.card.setFixedWidth(card_w)

    # ───────────────────────── 构建 ─────────────────────────

    def _build(self) -> None:
        repo = str(self._group.get('repo') or '尚未关联仓库')
        branch = str(self._group.get('branch') or 'main')
        self.set_subtitle(f'{repo} · {branch}')

        top = QHBoxLayout()
        top.setSpacing(6)
        self._btn_local = _ScopeButton('本机已推', '这台机器推送过的提交')
        self._btn_local.clicked.connect(lambda: self._switch('local'))
        top.addWidget(self._btn_local)
        self._btn_remote = _ScopeButton('远端仓库', '仓库里的提交（需要联网读取，'
                                                     '才有别处推上来的那些）')
        self._btn_remote.clicked.connect(lambda: self._switch('remote'))
        top.addWidget(self._btn_remote)
        top.addStretch(1)
        self._scope_hint = label('', theme.TEXT_FAINT, theme.FS_TINY)
        top.addWidget(self._scope_hint)
        self.body.addLayout(top)

        panes = QHBoxLayout()
        panes.setSpacing(12)
        panes.addWidget(self._build_list())

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
        self._view.setFixedHeight(PANES_H)
        self._view.setPlainText('正在读取提交历史…')
        self._painter = _DiffPainter(self._view.document())
        panes.addWidget(self._view, 1)
        self.body.addLayout(panes)

        self._btn_copy = self.add_ghost('复制本次差异')
        self._btn_copy.clicked.connect(self._copy)
        self.add_ghost('关闭').clicked.connect(self.accept)
        self._sync_scope()

    def _build_list(self) -> QWidget:
        self._list_scroll = QScrollArea()
        self._list_scroll.setObjectName('ScrollHost')
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_scroll.setFixedWidth(LIST_W)
        self._list_scroll.setFixedHeight(PANES_H)

        self._list_host = QWidget()
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(4, 4, 4, 4)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch(1)
        self._list_scroll.setWidget(self._list_host)
        return self._list_scroll

    # ───────────────────────── 数据 ─────────────────────────

    def set_commits(self, result: dict, *, scope: str = 'local') -> None:
        """喂入一次取回结果（``pipeline.commit_log`` 的返回值）。"""
        self._cache[scope] = result
        if scope == 'remote':
            self._remote_pending = False
        if scope != self._scope:
            return
        self._fill(result)

    def _fill(self, result: dict) -> None:
        # 清空列表（保留末尾的 stretch）
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        self._current_sha = ''

        commits = list(result.get('commits') or [])
        if not commits:
            self._list_lay.insertWidget(0, label(
                str(result.get('message') or '没有提交记录。'),
                theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))
            self._view.setPlainText(
                result.get('message') or '这里还没有任何提交。')
            return

        for c in commits:
            row = _CommitRow(c)
            row.clicked.connect(self._select)
            self._rows[str(c['sha'])] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)

        self._view.setPlainText('正在读取这次提交的内容…')
        self._select(str(commits[0]['sha']))

    def _select(self, sha: str) -> None:
        if sha == self._current_sha:
            return
        self._current_sha = sha
        for key, row in self._rows.items():
            row.set_selected(key == sha)
        self._view.setPlainText('正在读取这次提交的内容…')
        self.commit_selected.emit(sha)

    def set_patch(self, sha: str, text: str) -> None:
        """喂入某次提交的 diff。**过期的结果直接丢掉**（用户可能已经点到别处）。"""
        if sha != self._current_sha:
            return
        if not text.strip():
            self._view.setPlainText('这次提交没有可显示的文本改动（可能是空提交）。')
            return
        self._view.setPlainText(text)
        files, added, removed = _count_patch(text)
        self._scope_hint.setText(f'{files} 个文件 · +{added} −{removed}')

    # ───────────────────────── 范围切换 ─────────────────────────

    def _switch(self, scope: str) -> None:
        self._scope = scope
        self._sync_scope()
        cached = self._cache.get(scope)
        if cached is not None:
            self._fill(cached)
            return
        if scope == 'remote':
            self._view.setPlainText('正在联网读取远端仓库的提交历史…')
            # 已经在取了就别再发一次 —— 连点两下不该触发两轮 fetch
            if not self._remote_pending:
                self._remote_pending = True
                self.remote_requested.emit()

    def _sync_scope(self) -> None:
        self._btn_local.set_active(self._scope == 'local')
        self._btn_remote.set_active(self._scope == 'remote')
        self._scope_hint.setText('')

    def _copy(self) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._view.toPlainText())
        self._btn_copy.setText('已复制')

    # ───────────────────────── 尺寸 ─────────────────────────

    def sizeHint(self) -> QSize:  # noqa: D102
        return QSize(WIN_W, PANES_H + 200)
