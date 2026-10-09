# -*- coding: utf-8 -*-
"""账户页（设计稿 N-02）与退出登录确认（N-03）。

入口是右栏头部的账号胶囊（``@login``）—— 账号名在界面上一直显示，
但它得**能点**：用户想看「授权了什么权限、令牌存在哪、绑了哪些仓库」时，
不该跑去设置页翻。

页面上四块信息，按用户的关心程度排序：

    账号卡片        当前是谁、权限是什么、令牌是否正常
    凭据说明        令牌怎么存的 —— 被问起时直接指着这段回答
    已关联的仓库    哪些分组绑到了哪个仓库（退出登录**不会**动它们）
    退出登录        只清凭据，笔记和仓库配置原样保留

「多账号」是明确的暂不支持：同一时间只有一个账号，换账号 = 退出再授权。
界面上把这句话写出来，比让用户猜「能不能直接切号」要好。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QToolButton, QVBoxLayout)

from core import ghauth

from .. import account as account_mod, icons, theme

CARD_W = 620


def _label(text: str, color: str = theme.TEXT_MUTED, size: float = theme.FS_SMALL,
           weight: int = 400, mono: bool = False) -> QLabel:
    lab = QLabel(text)
    family = theme.MONO_STACK if mono else theme.UI_STACK
    lab.setStyleSheet(
        f'color: {color}; font-size: {size}px; font-weight: {weight};'
        f'font-family: {family};')
    lab.setWordWrap(True)
    return lab


class _Card(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('Card')
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(7)


class AccountDialog(QDialog):
    """账户信息 + 退出登录。``signed_out`` 发出后主窗口负责刷新界面。"""

    reauth_requested = Signal()
    signed_out = Signal()

    def __init__(self, account: account_mod.BoundAccount, groups: list[dict],
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._account = account
        self._groups = groups
        self._drag_from = None
        self._build()

    # ───────────────────────── 构建 ─────────────────────────

    def _build(self) -> None:
        self.setFixedWidth(CARD_W)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName('DialogCard')
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(12)

        # ── 标题栏 ──
        head = QFrame()
        head.setObjectName('DialogHeader')
        head.setFixedHeight(40)
        h = QHBoxLayout(head)
        h.setContentsMargins(16, 0, 10, 0)
        h.addWidget(_label('账户', theme.TEXT_STRONG, theme.FS_TITLE, 600))
        h.addStretch(1)
        close = QToolButton()
        close.setObjectName('WinBtn')
        close.setIcon(icons.icon('close', theme.TEXT_MUTED, 12))
        close.setIconSize(QSize(12, 12))
        close.setFixedSize(26, 26)
        close.setToolTip('关闭')
        close.setCursor(Qt.PointingHandCursor)
        close.setAutoRaise(True)
        close.clicked.connect(self.reject)
        h.addWidget(close)
        lay.addWidget(head)

        margin = QHBoxLayout()
        margin.setContentsMargins(16, 0, 16, 0)
        margin.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(12)
        margin.addLayout(col, 1)
        lay.addLayout(margin)

        col.addWidget(self._build_account_card())
        col.addWidget(self._build_secret_card())
        col.addWidget(self._build_repos_card())
        col.addWidget(self._build_signout_card())

        col.addWidget(self._build_multiaccount_note())

    def _build_account_card(self) -> QWidget:
        card = _Card()
        row = QHBoxLayout()
        row.setSpacing(12)

        # 头像：GitHub 没给本地缓存的头像就用首字母圆片 —— 下载图片不值当
        avatar = QLabel(self._account.login[:1].upper() or '?')
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f'background: {theme.PRIMARY}; color: #FFFFFF; border-radius: 20px;'
            f'font-size: 17px; font-weight: 600;')
        row.addWidget(avatar)

        info = QVBoxLayout()
        info.setSpacing(3)
        info.addWidget(_label(self._account.login, theme.TEXT_STRONG, 13.5, 600))
        scope = ghauth.DEFAULT_SCOPE.replace(' ', ', ')
        info.addWidget(_label(f'已通过 OAuth 授权 · 权限 {scope}',
                              theme.TEXT_SECOND, theme.FS_TINY))
        state = QHBoxLayout()
        state.setSpacing(8)
        if self._account.persisted:
            dot = QLabel('● 已连接')
            dot.setStyleSheet(f'color: {theme.SUCCESS}; font-size: {theme.FS_TINY}px;'
                              f'background: {theme.alpha(theme.SUCCESS, 0.14)};'
                              f'border-radius: 4px; padding: 2px 7px;')
            state.addWidget(dot)
            state.addWidget(_label('令牌已保存在本机', theme.TEXT_FAINT, theme.FS_TINY))
        else:
            warn = QLabel('● 仅本次会话')
            warn.setStyleSheet(f'color: {theme.WARNING}; font-size: {theme.FS_TINY}px;'
                               f'background: {theme.alpha(theme.WARNING, 0.14)};'
                               f'border-radius: 4px; padding: 2px 7px;')
            state.addWidget(warn)
            state.addWidget(_label('令牌没能写入本机，重启后需要重新授权',
                                   theme.TEXT_FAINT, theme.FS_TINY))
        state.addStretch(1)
        info.addLayout(state)
        row.addLayout(info, 1)

        reauth = QPushButton('重新授权')
        reauth.setObjectName('DialogButton')
        reauth.setFixedHeight(30)
        reauth.setCursor(Qt.PointingHandCursor)
        reauth.clicked.connect(self._on_reauth)
        row.addWidget(reauth)
        card.body.addLayout(row)
        return card

    def _build_secret_card(self) -> QWidget:
        card = _Card()
        card.body.addWidget(_label('凭据是怎么存的', theme.TEXT_MUTED,
                                   theme.FS_TINY, 600))
        backend, backend_label = account_mod.secret_backend()
        card.body.addWidget(_label(
            f'令牌用 {backend_label} 加密后存放在 ~/.pushnote/credentials/ 下。'
            '配置文件里只有账号名，没有令牌明文 —— 配置文件经常被拷来拷去，'
            '令牌不能混在里面。', theme.TEXT_SECOND, theme.FS_TINY))
        row = QHBoxLayout()
        row.addWidget(_label(backend, theme.TEXT_FAINT, theme.FS_TINY))
        row.addStretch(1)
        card.body.addLayout(row)
        return card

    def _build_repos_card(self) -> QWidget:
        card = _Card()
        card.body.addWidget(_label('已关联的仓库', theme.TEXT_MUTED,
                                   theme.FS_TINY, 600))
        if not self._groups:
            card.body.addWidget(_label('还没有分组关联仓库。',
                                       theme.TEXT_FAINT, theme.FS_TINY))
            return card
        card.body.addWidget(_label(
            '退出登录不会解除这些关联；重新登录后照常推送。',
            theme.TEXT_FAINT, theme.FS_TINY))
        for g in self._groups:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(str(g.get('name') or ''))
            name.setStyleSheet(f'color: {theme.TEXT_BODY}; font-size: {theme.FS_SMALL}px;')
            repo = QLabel(f'→  {g.get("repo") or "（还没关联仓库）"}')
            repo.setStyleSheet(
                f'color: {theme.TEXT_SECOND if g.get("repo") else theme.TEXT_FAINT};'
                f'font-size: {theme.FS_SMALL}px; font-family: {theme.MONO_STACK};')
            row.addWidget(name)
            row.addWidget(repo)
            row.addStretch(1)
            card.body.addLayout(row)
        return card

    def _build_signout_card(self) -> QWidget:
        card = _Card()
        self._signout_card = card
        card.body.addWidget(_label('退出登录', theme.TEXT_MUTED,
                                   theme.FS_TINY, 600))
        card.body.addWidget(_label(
            '退出后本机不再保存这个账号的令牌，需要重新授权才能推送。'
            '想换账号，就走这里。', theme.TEXT_SECOND, theme.FS_TINY))

        btn = QPushButton('退出登录')
        btn.setObjectName('DangerButton')
        btn.setFixedHeight(30)
        btn.setFixedWidth(96)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._show_signout_confirm)
        self._signout_btn = btn
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        card.body.addLayout(row)

        # 确认区：包进独立容器才能整块显隐 —— 布局本身没有 setVisible
        confirm_wrap = QFrame()
        confirm_lay = QVBoxLayout(confirm_wrap)
        confirm_lay.setContentsMargins(0, 0, 0, 0)
        confirm_lay.setSpacing(7)

        # N-03：先把「会变 / 不会变」说清楚，再把按钮递过去
        confirm_lay.addWidget(_label(
            '退出登录？笔记和仓库都不会动：本地 txt 原样保留，GitHub 上的内容也不变。',
            theme.TEXT_BODY, theme.FS_TINY))
        confirm_lay.addWidget(_label(
            '从这一刻起不能推送了，要重新授权才能继续。'
            '已关联的仓库、勾选过的文件都保留，重新登录后照常推送。',
            theme.TEXT_SECOND, theme.FS_TINY))

        btn_row = QHBoxLayout()
        cancel = QPushButton('取消')
        cancel.setObjectName('DialogButton')
        cancel.setFixedHeight(30)
        cancel.clicked.connect(self._hide_signout_confirm)
        sure = QPushButton('退出登录')
        sure.setObjectName('DangerButton')
        sure.setFixedHeight(30)
        sure.clicked.connect(self._do_signout)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(sure)
        confirm_lay.addLayout(btn_row)

        confirm_wrap.setVisible(False)
        self._confirm_wrap = confirm_wrap
        card.body.addWidget(confirm_wrap)
        return card

    def _build_multiaccount_note(self) -> QWidget:
        row = QHBoxLayout()
        row.setSpacing(8)
        tag = QLabel('多账号 · 暂不支持')
        tag.setStyleSheet(
            f'color: {theme.TEXT_FAINT}; font-size: {theme.FS_LABEL}px;'
            f'background: {theme.BG_CARD}; border: 1px solid {theme.BORDER};'
            f'border-radius: 4px; padding: 2px 7px;')
        row.addWidget(tag)
        row.addWidget(_label(
            '同一时间只连一个账号。分组绑定的仓库不受影响，重新登录后照常推送。',
            theme.TEXT_FAINT, theme.FS_TINY))
        row.addStretch(1)
        wrap = QFrame()
        wrap.setLayout(row)
        return wrap

    # ───────────────────────── 动作 ─────────────────────────

    def _on_reauth(self) -> None:
        self.accept()
        self.reauth_requested.emit()

    def _show_signout_confirm(self) -> None:
        """展开确认区。焦点默认落在取消侧 —— 这个操作可逆，不必做成红色恐吓。"""
        self._confirm_wrap.setVisible(True)
        self._signout_btn.setVisible(False)

    def _hide_signout_confirm(self) -> None:
        self._confirm_wrap.setVisible(False)
        self._signout_btn.setVisible(True)

    def _do_signout(self) -> None:
        self.accept()
        self.signed_out.emit()

    # ───────────────────────── 拖动 ─────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and event.position().y() <= 40:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(event)
