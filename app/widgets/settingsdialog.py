# -*- coding: utf-8 -*-
"""设置页（设计稿 V3-09）。

四张卡片，按「用户会想改什么」的顺序排：

    账号              当前连的是谁、授权了什么、要改去哪管理
    受管理的文件夹     哪些文件夹被纳入了同步，可以逐个解除绑定
    推送行为           三个开关 —— 决定点「推送」之后到底会发生什么
    关于               版本、项目地址、文件都存到哪了

与设计稿有两处偏差，都是它在画完之后发生的演进：

1. 稿子的账号卡片带「撤销授权」按钮。后来账户页（N-02）把这件事做全了
   （含凭据说明与二次确认），这里改成**入口**而不是再实现一遍 ——
   同一个动作两处实现，早晚会出现两处状态不一致。
2. 稿子的文案是「Push 前先确认提交信息」，界面文案后来统一成了中文。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QScrollArea, QVBoxLayout,
                               QWidget)

from core import config as core_config, ghauth

from .. import icons, theme
from .dialogbase import CheckButton, FramedDialog, label

CARD_W = 620
SCROLL_H = 560
#: 除滚动区之外，对话框还要占掉的高度（标题栏 + 底部按钮 + 外边距 + 余量）
CHROME_H = 210

#: 文件夹卡片最多铺几行，超出的用一行「等共 N 个」收尾（避免对话框无限长）
MAX_GROUP_ROWS = 4


class SettingsDialog(FramedDialog):
    """``exec()`` 只用来保持模态；实际动作都通过信号交回主窗口。"""

    #: 用户点了「管理账号」
    account_requested = Signal()
    #: 用户点了某个分组的「解除绑定」（带 group id）
    unbind_requested = Signal(str)
    #: 任何一个开关被改动（配置已写好，主窗口据此刷新界面）
    flags_changed = Signal()

    def __init__(self, cfg: dict, account, groups: list[dict], parent=None) -> None:
        super().__init__('设置', parent, icon_name='settings', width=CARD_W)
        self._cfg = cfg
        self._account = account
        self._groups = groups
        self._checks: dict[str, CheckButton] = {}
        self._build()
        self.finish()

    # ───────────────────────── 布局 ─────────────────────────

    def _build(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName('ScrollHost')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        host = QWidget()
        inner = QVBoxLayout(host)
        inner.setContentsMargins(0, 0, 6, 0)      # 右侧给滚动条留位置
        inner.setSpacing(7)

        inner.addWidget(self._section('账号'))
        inner.addWidget(self._account_card())
        inner.addWidget(self._section('受管理的文件夹'))
        inner.addWidget(self._groups_card())
        inner.addWidget(self._section('推送行为'))
        inner.addWidget(self._flags_card())
        inner.addWidget(self._section('关于'))
        inner.addWidget(self._about_card())
        inner.addStretch(1)

        scroll.setWidget(host)
        scroll.setFixedHeight(self._scroll_height())
        self.body.addWidget(scroll)

        self.add_ghost('关闭').clicked.connect(self.accept)

    def _scroll_height(self) -> int:
        """滚动区高度：优先铺满，但窗口小的时候必须收窄。

        主窗口最小可以缩到 900×560，写死高度会让对话框比窗口还高。
        所以按窗口实际高度算，内容多就让它滚动。
        """
        parent = self.parentWidget()
        win = parent.window() if parent is not None else None
        avail = (win.height() - CHROME_H) if win is not None else SCROLL_H
        return max(300, min(SCROLL_H, avail))

    def _section(self, text: str):
        lab = label(text, theme.TEXT_STRONG, theme.FS_UI, 600)
        lab.setContentsMargins(2, 4, 0, 0)
        return lab

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        box = QFrame()
        box.setObjectName('AuthStep')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(11)
        return box, lay

    # ───────────────────────── 账号 ─────────────────────────

    def _account_card(self) -> QFrame:
        box, lay = self._card()
        row = QHBoxLayout()
        row.setSpacing(11)

        login = getattr(self._account, 'login', '') or ''
        avatar = label(login[:1].upper() if login else '?',
                       theme.PRIMARY_HOVER, 15, 700)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(34, 34)
        avatar.setStyleSheet(
            f'color: {theme.PRIMARY_HOVER}; background: {theme.alpha(theme.PRIMARY, 0.2)};'
            f'border-radius: 17px; font-size: 15px; font-weight: 700;')
        row.addWidget(avatar)

        col = QVBoxLayout()
        col.setSpacing(3)
        if login:
            col.addWidget(label(login, theme.TEXT_STRONG, theme.FS_UI, 600))
            scope = ghauth.DEFAULT_SCOPE.replace(' ', ', ')
            col.addWidget(label(f'已通过 OAuth 授权 · 权限 {scope}',
                                theme.TEXT_FAINT, theme.FS_LABEL))
        else:
            col.addWidget(label('尚未绑定 GitHub 账号', theme.TEXT_MUTED,
                                theme.FS_UI, 600))
            col.addWidget(label('绑定之后才能推送与拉取', theme.TEXT_FAINT,
                                theme.FS_LABEL))
        row.addLayout(col, 1)

        if login:
            chip = label('已连接', theme.SUCCESS, theme.FS_LABEL, 600)
            chip.setStyleSheet(
                f'color: {theme.SUCCESS}; background: {theme.alpha(theme.SUCCESS, 0.14)};'
                f'border-radius: 4px; padding: 2px 7px; font-size: {theme.FS_LABEL}px;'
                f'font-weight: 600;')
            row.addWidget(chip, 0, Qt.AlignVCenter)

        manage = self._small_button('管理账号' if login else '去绑定')
        manage.clicked.connect(self.account_requested.emit)
        row.addWidget(manage, 0, Qt.AlignVCenter)
        lay.addLayout(row)
        return box

    # ───────────────────────── 受管理的文件夹 ─────────────────────────

    def _groups_card(self) -> QFrame:
        box, lay = self._card()
        if not self._groups:
            lay.addWidget(label('还没有纳入同步的文件夹。', theme.TEXT_MUTED,
                                theme.FS_SMALL))
            lay.addWidget(label('打开一个 txt，点右侧的「纳入 GitHub 管理」就能建立。',
                                theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))
            return box

        for g in self._groups[:MAX_GROUP_ROWS]:
            lay.addWidget(self._group_row(g))
        if len(self._groups) > MAX_GROUP_ROWS:
            lay.addWidget(label(f'等共 {len(self._groups)} 个',
                                theme.TEXT_FAINT, theme.FS_LABEL))
        return box

    def _group_row(self, group: dict) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        icon = label('', theme.TEXT_FAINT)
        icon.setPixmap(icons.icon('folder', theme.TEXT_SECOND, 16).pixmap(16, 16))
        icon.setFixedSize(16, 16)
        rl.addWidget(icon, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label(str(group.get('name') or group.get('id') or ''),
                            theme.TEXT_BODY, theme.FS_UI, 600))
        folder = str(group.get('folder') or '')
        col.addWidget(label(folder, theme.TEXT_FAINT, theme.FS_LABEL, wrap=False))
        repo = str(group.get('repo') or '')
        if repo:
            col.addWidget(label(f'→ {repo}', theme.TEXT_MUTED, theme.FS_LABEL))
        count = len(core_config.managed_names(group))
        col.addWidget(label(f'纳入 {count} 个文件', theme.TEXT_FAINT,
                            theme.FS_LABEL))
        rl.addLayout(col, 1)

        unbind = self._small_button('解除绑定', danger=True)
        unbind.clicked.connect(
            lambda _=False, gid=str(group.get('id') or ''):
            self.unbind_requested.emit(gid))
        rl.addWidget(unbind, 0, Qt.AlignTop)
        row.setToolTip('解除绑定只是不再同步这个文件夹，笔记文件本身不会被删除')
        return row

    # ───────────────────────── 推送行为 ─────────────────────────

    def _flags_card(self) -> QFrame:
        box, lay = self._card()
        for key in core_config.TOGGLE_KEYS:
            title, hint = core_config.TOGGLE_LABELS[key]
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(11)

            check = CheckButton(core_config.flag(self._cfg, key))
            check.clicked.connect(
                lambda _=False, k=key, c=check: self._on_toggle(k, c.isChecked()))
            rl.addWidget(check, 0, Qt.AlignTop)
            self._checks[key] = check

            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(label(title, theme.TEXT_BODY, theme.FS_UI))
            col.addWidget(label(hint, theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))
            rl.addLayout(col, 1)
            lay.addWidget(row)
        return box

    def _on_toggle(self, key: str, value: bool) -> None:
        """开关改动立即落盘 —— 设置页没有「保存」按钮，改完就是改完了。"""
        core_config.set_flag(self._cfg, key, value)
        try:
            core_config.save(self._cfg)
        except OSError:
            pass          # 保存失败不该打断操作；主窗口下次刷新会再提示
        self.flags_changed.emit()

    # ───────────────────────── 关于 ─────────────────────────

    def _about_card(self) -> QFrame:
        box, lay = self._card()
        # 只列三行：版本、项目地址、数据目录。工作区与备份都在数据目录底下，
        # 拆成三行会把卡片撑高、还会把有用的信息淹掉。
        rows = [
            ('版本', core_config.APP_VERSION),
            ('项目地址', 'github.com/freedom0213/FreePushNote'),
            ('数据目录', str(core_config.CONFIG_DIR)),
        ]
        for name, value in rows:
            row = QHBoxLayout()
            row.setSpacing(12)
            key = label(name, theme.TEXT_MUTED, theme.FS_SMALL)
            key.setFixedWidth(64)
            row.addWidget(key, 0, Qt.AlignTop)
            row.addWidget(label(value, theme.TEXT_FAINT, theme.FS_LABEL,
                                mono=True, wrap=True), 1)
            lay.addLayout(row)
        lay.addWidget(label('所有本地数据都在数据目录下；推送只读取你勾选的文件。',
                            theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))
        return box

    # ───────────────────────── 小控件 ─────────────────────────

    def _small_button(self, text: str, *, danger: bool = False):
        from PySide6.QtWidgets import QPushButton

        btn = QPushButton(text)
        btn.setObjectName('DangerButton' if danger else 'DialogButton')
        btn.setFixedHeight(30)
        btn.setMinimumWidth(84)
        btn.setCursor(Qt.PointingHandCursor)
        return btn
