# -*- coding: utf-8 -*-
"""底部状态栏（24px）。

五项之外，右边还有「归属」和「同步状态」——其中**归属**（当前文件属于哪个分组、
要推到哪个仓库）是最关键的一项，它防的是「推错仓库」。所以它放在右边、
颜色比左边的技术信息更亮一档。

左边是「只读的技术事实」，右边是「当前状态」，两者用中间的大片空白隔开。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from .. import theme

# 同步状态 → 颜色 / 圆点色
SYNC_STYLE = {
    'synced':    (theme.SUCCESS, '已同步'),
    'pending':   (theme.WARNING, '待推送'),
    'running':   (theme.WARNING, '推送中'),
    'failed':    (theme.ERROR, '推送失败'),
    'unmanaged': (theme.TEXT_WEAK, '未纳入管理'),
    'unlinked':  (theme.TEXT_WEAK, '未绑定账号'),
}


def _sep() -> QFrame:
    f = QFrame()
    f.setFixedSize(1, 11)
    f.setStyleSheet(f'background: {theme.BORDER};')
    return f


class StatusBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('StatusBar')
        self.setFixedHeight(theme.STATUSBAR_H)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)

        # ── 左组：技术事实 ──
        self._cursor = QLabel('行 1, 列 1')
        self._cursor.setObjectName('StatusTextMono')
        row.addWidget(self._cursor)

        row.addWidget(_sep())

        self._stats = QLabel('共 0 行 · 0 字')
        self._stats.setObjectName('StatusFaint')   # 刻意压暗，不抢眼
        row.addWidget(self._stats)

        row.addWidget(_sep())

        self._encoding = QLabel('UTF-8')
        self._encoding.setObjectName('StatusTextMono')
        row.addWidget(self._encoding)

        row.addWidget(_sep())

        self._eol = QLabel('CRLF')
        self._eol.setObjectName('StatusTextMono')
        row.addWidget(self._eol)

        row.addStretch(1)

        # ── 右组：归属 + 同步状态 ──
        self._owner = QLabel('未纳入 GitHub 管理')
        self._owner.setObjectName('StatusTextMono')
        self._owner.setStyleSheet(f'color: {theme.TEXT_WEAK}; font-family: {theme.MONO_STACK};')
        self._owner.setToolTip('当前文件属于哪个分组、会推到哪个仓库')
        row.addWidget(self._owner)

        row.addWidget(_sep())

        self._sync_dot = QLabel()
        self._sync_dot.setFixedSize(6, 6)
        row.addWidget(self._sync_dot)

        self._sync_text = QLabel('未纳入管理')
        self._sync_text.setObjectName('StatusText')
        row.addWidget(self._sync_text)

        self.set_sync('unmanaged')

    # ───────────────────────── 对外接口 ─────────────────────────

    def set_cursor(self, line: int, col: int) -> None:
        self._cursor.setText(f'行 {line}, 列 {col}')

    def set_stats(self, lines: int, chars: int) -> None:
        self._stats.setText(f'共 {lines} 行 · {chars} 字')

    def set_encoding(self, name: str, warn: bool = False) -> None:
        """``warn=True`` 表示不是 UTF-8（推送后 GitHub 上可能乱码）。"""
        color = theme.WARNING if warn else theme.TEXT_MUTED
        self._encoding.setText(name)
        self._encoding.setStyleSheet(
            f'color: {color}; font-family: {theme.MONO_STACK}; font-size: {theme.FS_SMALL}px;')
        self._encoding.setToolTip('该文件不是 UTF-8，推送后可能显示乱码' if warn else '文件编码')

    def set_eol(self, name: str, warn: bool = False) -> None:
        """``warn=True`` 表示本地是 CRLF（推送时会转成 LF 存储）。"""
        color = theme.WARNING if warn else theme.TEXT_MUTED
        self._eol.setText(name)
        self._eol.setStyleSheet(
            f'color: {color}; font-family: {theme.MONO_STACK}; font-size: {theme.FS_SMALL}px;')
        self._eol.setToolTip('本地为 CRLF，推送时会转为 LF' if warn else '换行符')

    def set_owner(self, group: str | None, repo: str | None) -> None:
        if group and repo:
            self._owner.setText(f'{group} → {repo}')
            self._owner.setStyleSheet(
                f'color: {theme.TEXT_BODY}; font-family: {theme.MONO_STACK}; '
                f'font-size: {theme.FS_SMALL}px;')
        else:
            self._owner.setText('未纳入 GitHub 管理')
            self._owner.setStyleSheet(
                f'color: {theme.TEXT_WEAK}; font-family: {theme.MONO_STACK}; '
                f'font-size: {theme.FS_SMALL}px;')

    def set_sync(self, state: str, detail: str = '') -> None:
        """``state`` 取 SYNC_STYLE 的键；``detail`` 是时间等附加信息。"""
        color, label = SYNC_STYLE.get(state, SYNC_STYLE['unmanaged'])
        text = f'{label} · {detail}' if detail else label
        self._sync_dot.setStyleSheet(f'background: {color}; border-radius: 3px;')
        self._sync_text.setText(text)
        self._sync_text.setStyleSheet(
            f'color: {color}; font-size: {theme.FS_SMALL}px; font-weight: 600;')
