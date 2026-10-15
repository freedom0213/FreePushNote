# -*- coding: utf-8 -*-
"""底部状态栏（24px）。

五项之外，右边还有「归属」和「同步状态」——其中**归属**（当前文件属于哪个分组、
要推到哪个仓库）是最关键的一项，它防的是「推错仓库」。所以它放在右边、
颜色比左边的技术信息更亮一档。

左边是「只读的技术事实」，右边是「当前状态」，两者用中间的大片空白隔开。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from .. import icons, theme

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


class _CodeItem(QFrame):
    """状态栏里的编码 / 换行项（设计稿 S-03）。

    正常时是一段灰字；**异常时变成琥珀色胶囊、而且可以点**。为什么值得做成能点的
    东西：状态栏只有 24px，一个孤零零的 ``GBK`` 没人会去理解它的后果；变成胶囊 +
    可点之后，才有机会把「推送后 GitHub 上可能显示乱码」这句话送到用户面前。

    刻意**不自动弹卡**：体检结果不该打断正在写东西的人。用户想了解时点一下，
    这就是全部交互（与设计稿图注一致）。
    """

    clicked = Signal()

    def __init__(self, tooltip: str = '', parent=None) -> None:
        super().__init__(parent)
        self._value = ''
        self._warn = False
        self._hover = False
        self._icon_name = 'alert-circle'
        self._base_tip = tooltip
        self.setFixedHeight(16)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)

        self._icon = QLabel()
        self._icon.setFixedSize(11, 11)
        self._icon.setVisible(False)
        row.addWidget(self._icon)

        self._text = QLabel('')
        row.addWidget(self._text)
        self._restyle()

    # ───────────────────────── 对外 ─────────────────────────

    def value(self) -> str:
        return self._value

    def is_warning(self) -> bool:
        return self._warn

    def set_value(self, name: str, warn: bool = False,
                  icon_name: str = 'alert-circle', tip: str = '') -> None:
        self._value = str(name)
        self._warn = bool(warn)
        self._icon_name = icon_name
        self._text.setText(self._value)
        self._icon.setVisible(self._warn)
        self._restyle()
        self.setCursor(Qt.PointingHandCursor if self._warn else Qt.ArrowCursor)
        self.setToolTip(tip or self._base_tip)

    # ───────────────────────── 内部 ─────────────────────────

    def _restyle(self) -> None:
        lay = self.layout()
        if lay is not None:
            # 胶囊要给文字留出内边距；正常态则和旁边的状态栏文字对齐
            lay.setContentsMargins(6 if self._warn else 0, 0,
                                   6 if self._warn else 0, 0)
        if self._warn:
            self._icon.setPixmap(
                icons.icon(self._icon_name, theme.WARNING, 11).pixmap(11, 11))
            strength = 0.26 if self._hover else 0.16
            self.setStyleSheet(
                f'background: {theme.alpha(theme.WARNING, strength)};'
                f'border-radius: 3px;')
            self._text.setStyleSheet(
                f'color: {theme.WARNING}; font-family: {theme.MONO_STACK};'
                f'font-size: {theme.FS_LABEL}px; font-weight: 500;')
        else:
            self.setStyleSheet('background: transparent;')
            self._text.setStyleSheet(
                f'color: {theme.TEXT_MUTED}; font-family: {theme.MONO_STACK};'
                f'font-size: {theme.FS_SMALL}px;')

    def enterEvent(self, event) -> None:  # noqa: N802
        # QLabel/QFrame 的 QSS :hover 在 Qt 里默认不生效（要 WA_Hover），
        # 所以悬停态自己维护 —— 可点的东西必须给一点反馈，否则用户不知道它能点。
        self._hover = True
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._restyle()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._warn and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class StatusBar(QFrame):
    #: 点编码 / 换行那两项的琥珀胶囊 → 打开「编码与换行符提醒」卡（设计稿 S-03）
    health_clicked = Signal()

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

        self._encoding = _CodeItem('文件编码')
        self._encoding.clicked.connect(self.health_clicked)
        row.addWidget(self._encoding)

        row.addWidget(_sep())

        self._eol = _CodeItem('换行符')
        self._eol.clicked.connect(self.health_clicked)
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
        """``warn=True`` 表示不是 UTF-8（推送后 GitHub 上可能乱码）。

        异常时这一项会变成可点的琥珀胶囊，点开是「编码与换行符提醒」卡。
        """
        self._encoding.set_value(
            name, warn, icon_name='alert-circle',
            tip=('点开看看这条编码会有什么影响' if warn else '文件编码'))

    def set_eol(self, name: str, warn: bool = False) -> None:
        """``warn=True`` 表示本地是 CRLF（推送时会转成 LF 存储，本地文件不变）。"""
        self._eol.set_value(
            name, warn, icon_name='info-circle',
            tip=('点开看看这条换行符会有什么影响' if warn else '换行符'))

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
