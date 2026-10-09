# -*- coding: utf-8 -*-
"""右侧栏（300px）与它的收起窄条（48px）。

这是 v3 布局里最核心的一处调整：**所有推送相关的信息集中在这里**，
不散落在左下角、不显示 git 命令。自上而下依次是

    仓库卡片        当前文件属于哪个分组 → 哪个仓库 / 分支 / 仓库内路径
    同步状态卡片    已同步 / 有改动待推送 / 推送中 / 推送失败，配一句人话说明
    Push 主按钮     这一屏唯一的主动作
    Pull / 查看差异  低频次要动作
    待推送变更      有改动时才出现，点了能看到这次会推哪些文件
    最近推送        哈希 + 提交信息 + 相对时间

状态一律用**结果词**，界面上不出现 ``commit`` / ``origin`` / ``staged``。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from .. import icons, theme

# 同步状态 → (圆点色, 主文案, 英文标记, 说明文案)
SYNC_STATES = {
    'synced':    (theme.SUCCESS, '已同步', 'SYNCED', '本地内容与 GitHub 一致，没有待推送的改动'),
    'pending':   (theme.WARNING, '有改动待推送', 'PENDING', '有本地改动还没推上去'),
    'running':   (theme.WARNING, '推送中', 'PUSHING', '正在把改动推到 GitHub'),
    'failed':    (theme.ERROR, '推送失败', 'FAILED', '改动已保存在本地，可以重试'),
    'unmanaged': (theme.TEXT_WEAK, '未纳入管理', 'UNMANAGED', '这个文件没有关联到任何 GitHub 仓库'),
    'unlinked':  (theme.TEXT_WEAK, '未绑定账号', 'UNLINKED', '绑定 GitHub 账号后，才能把笔记推送到仓库'),
}


class _Card(QFrame):
    """通用卡片容器。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('Card')
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(8)

    def set_danger(self, danger: bool) -> None:
        self.setObjectName('CardError' if danger else 'Card')
        self.style().unpolish(self)
        self.style().polish(self)


def _label(text: str, color: str = theme.TEXT_MUTED, size: float = theme.FS_TINY,
           weight: int = 400, mono: bool = False) -> QLabel:
    lab = QLabel(text)
    family = theme.MONO_STACK if mono else theme.UI_STACK
    lab.setStyleSheet(
        f'color: {color}; font-size: {size}px; font-weight: {weight}; font-family: {family};')
    return lab


class PushPanel(QFrame):
    """右侧栏 300px。"""

    collapse_requested = Signal()
    push_requested = Signal()
    pull_requested = Signal()
    diff_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('PushPanel')
        self.setFixedWidth(theme.PANEL_W)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(14, 14, 14, 0)
        self._body.setSpacing(12)

        self._body.addWidget(self._build_repo_card())
        self._body.addWidget(self._build_status_card())
        self._body.addWidget(self._build_push_area())
        self._body.addWidget(self._build_secondary_row())
        self._body.addWidget(self._build_changes())
        self._body.addWidget(self._build_history())
        self._body.addStretch(1)

        root.addWidget(body, 1)

        self.set_sync_state('unmanaged')
        self.set_push_state('disabled')
        self.set_repo(None, None, None)
        self.set_changes([])
        self.set_history([])

    # ───────────────────────── 头部 ─────────────────────────

    def _build_header(self) -> QWidget:
        head = QFrame()
        head.setObjectName('PanelHeader')
        head.setFixedHeight(44)
        lay = QHBoxLayout(head)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(8)

        title = QLabel('FreePush')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;')
        lay.addWidget(title)

        chip = QLabel('v0.1')
        chip.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: 10px; background: #38383C;'
            f'border-radius: 4px; padding: 2px 6px; font-family: {theme.MONO_STACK};')
        lay.addWidget(chip)

        # 已连接的账号。绑完之后界面上得有地方一直显示它 ——
        # 否则用户没法一眼确认「我推的是哪个账号」，推错账号是很难发现的错误。
        self._account_chip = QLabel('')
        self._account_chip.setVisible(False)
        lay.addWidget(self._account_chip)

        lay.addStretch(1)

        btn = QToolButton()
        btn.setObjectName('WinBtn')
        btn.setIcon(icons.icon('panel-right-hide', theme.TEXT_MUTED, 14))
        btn.setIconSize(QSize(14, 14))
        btn.setFixedSize(24, 24)
        btn.setToolTip('收起面板')
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.clicked.connect(self.collapse_requested)
        lay.addWidget(btn)
        return head

    # ───────────────────────── 仓库卡片 ─────────────────────────

    def _build_repo_card(self) -> QWidget:
        card = _Card()
        self._repo_card = card

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._repo_name = QLabel('尚未关联仓库')
        self._repo_name.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;')
        row1.addWidget(self._repo_name)
        row1.addStretch(1)

        self._branch_chip = QLabel('main')
        self._branch_chip.setStyleSheet(
            f'color: {theme.TEXT_BODY}; font-size: 10.5px; background: #38383C;'
            f'border-radius: 4px; padding: 3px 7px; font-family: {theme.MONO_STACK};')
        row1.addWidget(self._branch_chip)
        card.body.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(7)
        self._path_icon = QLabel()
        self._path_icon.setPixmap(icons.icon('file', '#7A7A7A', 13).pixmap(13, 13))
        row2.addWidget(self._path_icon)
        self._repo_path = _label('绑定账号后，从你的仓库列表里选一个',
                                 theme.TEXT_SECOND, theme.FS_SMALL, mono=True)
        row2.addWidget(self._repo_path)
        row2.addStretch(1)
        card.body.addLayout(row2)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f'background: {theme.BORDER};')
        card.body.addWidget(divider)

        row3 = QHBoxLayout()
        self._last_sync = _label('还没有同步过', theme.TEXT_MUTED, theme.FS_TINY)
        row3.addWidget(self._last_sync)
        row3.addStretch(1)
        self._last_hash = _label('', theme.TEXT_WEAK, theme.FS_LABEL, mono=True)
        row3.addWidget(self._last_hash)
        card.body.addLayout(row3)
        return card

    # ───────────────────────── 同步状态卡片 ─────────────────────────

    def _build_status_card(self) -> QWidget:
        card = _Card()
        self._status_card = card

        row = QHBoxLayout()
        row.setSpacing(7)
        self._status_dot = QFrame()
        self._status_dot.setFixedSize(8, 8)
        row.addWidget(self._status_dot)

        self._status_title = QLabel('未纳入管理')
        self._status_title.setStyleSheet(
            f'color: {theme.TEXT_WEAK}; font-size: 13px; font-weight: 600;')
        row.addWidget(self._status_title)
        row.addStretch(1)

        self._status_tag = _label('UNMANAGED', theme.TEXT_WEAK, 10, mono=True)
        row.addWidget(self._status_tag)
        card.body.addLayout(row)

        self._status_desc = QLabel('这个文件没有关联到任何 GitHub 仓库')
        self._status_desc.setWordWrap(True)
        self._status_desc.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FS_TINY}px; line-height: 17px;')
        card.body.addWidget(self._status_desc)
        return card

    # ───────────────────────── Push 按钮区 ─────────────────────────

    def _build_push_area(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.push_button = QPushButton('打开一个文件后可推送')
        self.push_button.setObjectName('PushButton')
        self.push_button.setFixedHeight(42)
        self.push_button.setCursor(Qt.PointingHandCursor)
        self.push_button.setIconSize(QSize(16, 16))
        self.push_button.clicked.connect(self.push_requested)
        lay.addWidget(self.push_button)

        self._hotkey = _label('Ctrl + Enter', theme.TEXT_FAINT, 10, mono=True)
        self._hotkey.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._hotkey)
        return wrap

    # ───────────────────────── 次要动作 ─────────────────────────

    def _build_secondary_row(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.btn_pull = QPushButton('  Pull')
        self.btn_pull.setObjectName('GhostButton')
        self.btn_pull.setFixedHeight(32)
        self.btn_pull.setIcon(icons.icon('pull', theme.TEXT_BODY, 14))
        self.btn_pull.setIconSize(QSize(14, 14))
        self.btn_pull.setCursor(Qt.PointingHandCursor)
        self.btn_pull.clicked.connect(self.pull_requested)
        lay.addWidget(self.btn_pull)

        self.btn_diff = QPushButton('  查看差异')
        self.btn_diff.setObjectName('GhostButton')
        self.btn_diff.setFixedHeight(32)
        self.btn_diff.setIcon(icons.icon('diff', theme.TEXT_BODY, 14))
        self.btn_diff.setIconSize(QSize(14, 14))
        self.btn_diff.setCursor(Qt.PointingHandCursor)
        self.btn_diff.clicked.connect(self.diff_requested)
        lay.addWidget(self.btn_diff)
        return wrap

    # ───────────────────────── 待推送变更 ─────────────────────────

    def _build_changes(self) -> QWidget:
        wrap = QWidget()
        self._changes_wrap = wrap
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(9)

        head = QHBoxLayout()
        head.addWidget(_label('待推送变更', theme.TEXT_MUTED, theme.FS_TINY, 600))
        head.addStretch(1)
        self._changes_summary = _label('', theme.WARNING, theme.FS_LABEL, mono=True)
        head.addWidget(self._changes_summary)
        lay.addLayout(head)

        self._changes_box = QVBoxLayout()
        self._changes_box.setSpacing(6)
        lay.addLayout(self._changes_box)
        return wrap

    # ───────────────────────── 最近推送 ─────────────────────────

    def _build_history(self) -> QWidget:
        wrap = QWidget()
        self._history_wrap = wrap
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(9)

        head = QHBoxLayout()
        head.addWidget(_label('最近推送', theme.TEXT_MUTED, theme.FS_TINY, 600))
        head.addStretch(1)
        self._history_all = _label('全部记录', theme.TEXT_WEAK, theme.FS_TINY)
        head.addWidget(self._history_all)
        lay.addLayout(head)

        self._history_box = QVBoxLayout()
        self._history_box.setSpacing(8)
        lay.addLayout(self._history_box)
        return wrap

    # ───────────────────────── 对外接口 ─────────────────────────

    def set_repo(self, repo: str | None, branch: str | None, path: str | None,
                 group: str | None = None) -> None:
        if repo:
            self._repo_name.setText(repo)
            self._repo_name.setStyleSheet(
                f'color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;')
            self._branch_chip.setText(branch or 'main')
            self._branch_chip.setVisible(True)
            self._repo_path.setText(path or '')
            self._path_icon.setVisible(True)
        else:
            self._repo_name.setText('尚未关联仓库')
            self._repo_name.setStyleSheet(
                f'color: {theme.TEXT_SECOND}; font-size: 12px; font-weight: 600;')
            self._branch_chip.setVisible(False)
            self._repo_path.setText('绑定账号后，从你的仓库列表里选一个')
            self._path_icon.setVisible(False)
        self._repo_name.setToolTip(group or '')

    def set_account(self, login: str | None, warn: bool = False) -> None:
        """面板头部显示当前连接的 GitHub 账号。

        ``warn=True`` 表示凭据可能失效（比如令牌被撤销），用琥珀色提醒。
        """
        if not login:
            self._account_chip.setVisible(False)
            return
        color = theme.WARNING if warn else theme.SUCCESS
        self._account_chip.setText(f'@{login}')
        self._account_chip.setStyleSheet(
            f'color: {color}; font-size: 10px;'
            f'background: {theme.alpha(color, 0.14)};'
            f'border-radius: 4px; padding: 2px 6px;'
            f'font-family: {theme.MONO_STACK};')
        self._account_chip.setToolTip(
            '账号凭据可能已失效，建议重新授权' if warn else '已连接的 GitHub 账号')
        self._account_chip.setVisible(True)

    def set_last_sync(self, relative: str | None, short_hash: str | None = None) -> None:
        self._last_sync.setText(f'上次同步 {relative}' if relative else '还没有同步过')
        self._last_hash.setText(short_hash or '')

    def set_sync_state(self, state: str, desc: str | None = None) -> None:
        color, title, tag, default_desc = SYNC_STATES.get(state, SYNC_STATES['unmanaged'])
        self._status_dot.setStyleSheet(f'background: {color}; border-radius: 4px;')
        self._status_title.setText(title)
        self._status_title.setStyleSheet(
            f'color: {color}; font-size: 13px; font-weight: 600;')
        self._status_tag.setText(tag)
        self._status_desc.setText(desc or default_desc)
        self._status_card.set_danger(state == 'failed')

    def set_push_state(self, state: str, text: str | None = None,
                       icon_name: str | None = None) -> None:
        """``state``: disabled | ready | running | success | failed

        ``icon_name`` 用于「按钮文案变了、图标也该跟着换」的场合
        （例如未绑账号时按钮是「绑定 GitHub 账号」，配 GitHub 图标才不别扭）。
        """
        labels = {
            'disabled': '打开一个文件后可推送',
            'ready': 'Push 到 GitHub',
            'running': '推送中…',
            'success': '已推送',
            'failed': '重试推送',
            'uptodate': '已是最新，无需推送',
        }
        self.push_button.setText(text or labels.get(state, 'Push 到 GitHub'))
        self.push_button.setProperty('state', state)
        self.push_button.style().unpolish(self.push_button)
        self.push_button.style().polish(self.push_button)

        self.push_button.setEnabled(
            state in ('ready', 'failed', 'running', 'success', 'uptodate'))
        name = icon_name or ('check-circle' if state == 'success' else 'push')
        color = {'running': '#A6BDCD', 'success': theme.BG_APP,
                 'uptodate': theme.TEXT_MUTED}.get(
            state, '#FFFFFF' if state in ('ready', 'failed') else theme.TEXT_MUTED)
        self.push_button.setIcon(icons.icon(name, color, 16))
        self._hotkey.setVisible(state in ('ready', 'failed'))

        for b in (self.btn_pull, self.btn_diff):
            b.setEnabled(state != 'running')

    def set_changes(self, changes: list[dict]) -> None:
        """``changes`` = [{name, added, removed}, ...]；空列表则整块隐藏。"""
        while self._changes_box.count():
            item = self._changes_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        total_add = sum(int(c.get('added', 0)) for c in changes)
        total_del = sum(int(c.get('removed', 0)) for c in changes)
        self._changes_summary.setText(
            f'{len(changes)} 个文件 · +{total_add} −{total_del}' if changes else '')

        for c in changes:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            dot = QFrame()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet(f'background: {theme.WARNING}; border-radius: 3px;')
            lay.addWidget(dot)

            name = _label(c.get('name', ''), theme.TEXT_BODY, theme.FS_SMALL, mono=True)
            name.setToolTip(c.get('path', ''))
            lay.addWidget(name, 1)

            lay.addWidget(_label(f"+{c.get('added', 0)}", theme.SUCCESS,
                                 theme.FS_LABEL, 500, mono=True))
            lay.addWidget(_label(f"−{c.get('removed', 0)}", theme.ERROR,
                                 theme.FS_LABEL, 500, mono=True))
            self._changes_box.addWidget(row)

        self._changes_wrap.setVisible(bool(changes))

    def set_history(self, records: list[dict]) -> None:
        """``records`` = [{hash, message, relative}, ...]"""
        while self._history_box.count():
            item = self._history_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not records:
            self._history_box.addWidget(
                _label('还没有推送记录', theme.TEXT_FAINT, theme.FS_SMALL))
            return

        for r in records[:3]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            lay.addWidget(_label(r.get('hash', ''), theme.TEXT_FAINT,
                                 theme.FS_LABEL, mono=True))
            msg = _label(r.get('message', ''), theme.TEXT_BODY, theme.FS_SMALL)
            msg.setToolTip(r.get('message', ''))
            lay.addWidget(msg, 1)
            lay.addWidget(_label(r.get('relative', ''), theme.TEXT_FAINT,
                                 theme.FS_LABEL, mono=True))
            self._history_box.addWidget(row)


class PanelRail(QFrame):
    """右栏收起后的 48px 窄条：状态灯 + Push 图标按钮 + 底部设置。"""

    expand_requested = Signal()
    push_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('PushPanel')
        self.setFixedWidth(theme.PANEL_RAIL_W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        expand = QToolButton()
        expand.setObjectName('WinBtn')
        expand.setIcon(icons.icon('panel-right-hide', theme.TEXT_SECOND, 14))
        expand.setIconSize(QSize(14, 14))
        expand.setFixedSize(theme.PANEL_RAIL_W, 44)
        expand.setToolTip('展开面板')
        expand.setCursor(Qt.PointingHandCursor)
        expand.setAutoRaise(True)
        expand.clicked.connect(self.expand_requested)
        lay.addWidget(expand)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f'background: {theme.BORDER};')
        lay.addWidget(div)

        lay.addSpacing(18)

        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f'background: {theme.TEXT_WEAK}; border-radius: 4px;')
        dot_row = QHBoxLayout()
        dot_row.addStretch(1)
        dot_row.addWidget(self._dot)
        dot_row.addStretch(1)
        lay.addLayout(dot_row)

        lay.addSpacing(14)

        push = QToolButton()
        push.setObjectName('WinBtn')
        push.setIcon(icons.icon('push', theme.PRIMARY, 16))
        push.setIconSize(QSize(16, 16))
        push.setFixedSize(36, 36)
        push.setToolTip('Push 到 GitHub（Ctrl+Enter）')
        push.setCursor(Qt.PointingHandCursor)
        push.clicked.connect(self.push_requested)
        push_row = QHBoxLayout()
        push_row.addStretch(1)
        push_row.addWidget(push)
        push_row.addStretch(1)
        lay.addLayout(push_row)
        self._push_btn = push

        lay.addStretch(1)

        gear = QToolButton()
        gear.setObjectName('WinBtn')
        gear.setIcon(icons.icon('settings', theme.TEXT_SECOND, 16))
        gear.setIconSize(QSize(16, 16))
        gear.setFixedSize(34, 34)
        gear.setToolTip('设置')
        gear.setCursor(Qt.PointingHandCursor)
        gear.setAutoRaise(True)
        gear.clicked.connect(self.settings_requested)
        gear_row = QHBoxLayout()
        gear_row.addStretch(1)
        gear_row.addWidget(gear)
        gear_row.addStretch(1)
        lay.addLayout(gear_row)
        lay.addSpacing(14)

    def set_sync_state(self, state: str) -> None:
        color = SYNC_STATES.get(state, SYNC_STATES['unmanaged'])[0]
        self._dot.setStyleSheet(f'background: {color}; border-radius: 4px;')
