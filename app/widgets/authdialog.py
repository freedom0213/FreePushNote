# -*- coding: utf-8 -*-
"""绑定 GitHub 账号的对话框（OAuth Device Flow）。

界面上的三件事，顺序不能乱：

    ① 复制验证码     8 位码，是全屏唯一「大而显眼」的文字
    ② 打开授权页     直接把码带在链接里跳过去，用户不用手打
    ③ 等结果         倒计时 + 一句人话状态；成功后窗口自己关掉

失败时按 :mod:`core.ghauth` 的错误种类给不同文案，**不做成一句「认证失败」**——
「连不上 GitHub」和「你在网页上点了拒绝」对用户来说是完全不同的两件事：
前者要重试，后者要看说明才知道自己拒了什么。

令牌的保存在 :mod:`app.account`，本模块只负责把它拿到手。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QPushButton, QToolButton,
                               QVBoxLayout)

from core import ghauth

from .. import account as account_mod, icons, theme

CARD_W = 452

#: 运行中的认证线程。**必须持引用** —— 否则 QThread 被 GC 掉会导致进程崩溃。
#: 线程结束时自己摘掉；即使对话框已经关闭，它也能安全地跑完。
_LIVE_WORKERS: set['_AuthWorker'] = set()


class _AuthWorker(QThread):
    """把三步协议放到后台线程，界面全程不卡。"""

    code_ready = Signal(object)          # DeviceCode
    pending = Signal(float)              # 剩余秒数
    succeeded = Signal(object, object)   # Token, Account
    failed = Signal(object)              # AuthError

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        try:
            token, acc = ghauth.authorize(
                None,                                  # 用内置 client_id
                on_code=self.code_ready.emit,
                should_cancel=lambda: self._cancelled,
                on_pending=self.pending.emit,
            )
        except ghauth.AuthError as exc:
            if not self._cancelled and exc.kind != ghauth.KIND_CANCELLED:
                self.failed.emit(exc)
        except Exception as exc:  # noqa: BLE001 - 兜底：绝不让异常把线程带崩
            if not self._cancelled:
                self.failed.emit(ghauth.AuthError(
                    ghauth.KIND_API, '授权过程中出现了意外错误。', repr(exc)))
        else:
            if not self._cancelled:
                self.succeeded.emit(token, acc)


def _label(text: str, color: str = theme.TEXT_MUTED, size: float = theme.FS_SMALL,
           weight: int = 400, mono: bool = False) -> QLabel:
    lab = QLabel(text)
    family = theme.MONO_STACK if mono else theme.UI_STACK
    lab.setStyleSheet(
        f'color: {color}; font-size: {size}px; font-weight: {weight};'
        f'font-family: {family};')
    return lab


#: 错误种类 → (标题, 给用户的建议)
_ERROR_TEXT = {
    ghauth.KIND_NETWORK: ('连不上 GitHub',
                          '检查一下网络，或者确认代理软件正在运行。'),
    ghauth.KIND_DENIED:  ('你在 GitHub 上拒绝了这次授权',
                          '如果你改主意了，点「重试」再来一次即可。'),
    ghauth.KIND_EXPIRED: ('验证码已过期',
                          '验证码只有 15 分钟有效期。点「重试」会生成一个新的。'),
    ghauth.KIND_API:     ('GitHub 拒绝了这次请求', ''),
    ghauth.KIND_PARSE:   ('GitHub 的响应无法解析',
                          '常见原因是代理软件把请求换成了自己的页面。'),
    ghauth.KIND_CONFIG:  ('还没有配置 OAuth 应用',
                          '请在 core/ghauth.py 里填入 client_id。'),
}


class GitHubAuthDialog(QDialog):
    """绑定账号。成功后 :attr:`account` 里是 :class:`app.account.BoundAccount`。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        self._worker: _AuthWorker | None = None
        self._device: ghauth.DeviceCode | None = None
        self._remaining = 0.0
        self._drag_from = None

        self.account: account_mod.BoundAccount | None = None
        self.persisted = True        # 令牌是否成功落盘

        self._countdown = QTimer(self)
        self._countdown.setInterval(500)
        self._countdown.timeout.connect(self._tick)

        self._build()
        self._apply_state('starting')

    # ───────────────────────── 构建 ─────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)   # 留给阴影

        card = QFrame()
        card.setObjectName('DialogCard')
        card.setFixedWidth(CARD_W)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(44)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 180))
        card.setGraphicsEffect(shadow)

        col = QVBoxLayout(card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_header())
        col.addWidget(self._build_body())
        col.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        head = QFrame()
        head.setObjectName('DialogHeader')
        head.setFixedHeight(52)
        lay = QHBoxLayout(head)
        lay.setContentsMargins(20, 0, 14, 0)
        lay.setSpacing(9)

        logo = QLabel()
        logo.setPixmap(icons.icon('github', theme.TEXT_BODY, 16).pixmap(16, 16))
        lay.addWidget(logo)

        title = QLabel('绑定 GitHub 账号')
        title.setStyleSheet(
            f'color: {theme.TEXT_STRONG}; font-size: 14px; font-weight: 600;')
        lay.addWidget(title)
        lay.addStretch(1)

        close = QToolButton()
        close.setObjectName('WinBtn')
        close.setIcon(icons.icon('close', theme.TEXT_MUTED, 12))
        close.setIconSize(QSize(12, 12))
        close.setFixedSize(26, 26)
        close.setCursor(Qt.PointingHandCursor)
        close.setAutoRaise(True)
        close.setToolTip('取消绑定')
        close.clicked.connect(self.reject)
        lay.addWidget(close)
        return head

    def _build_body(self) -> QFrame:
        body = QFrame()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 18, 20, 0)
        lay.setSpacing(12)

        desc = _label('授权不需要输入密码。FreePushNote 只是拿到一枚令牌，'
                      '用来把你的笔记推到仓库。', theme.TEXT_SECOND,
                      theme.FS_SMALL)
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # ① 验证码
        lay.addWidget(_label('① 复制这串验证码', theme.TEXT_MUTED,
                             theme.FS_TINY, 600))

        code_row = QHBoxLayout()
        code_row.setSpacing(8)
        self._code = QLabel('— — — — — — — —')
        self._code.setObjectName('AuthCode')
        self._code.setAlignment(Qt.AlignCenter)
        self._code.setFixedHeight(56)
        code_row.addWidget(self._code, 1)

        self._btn_copy = QPushButton(' 复制')
        self._btn_copy.setObjectName('DialogButton')
        self._btn_copy.setFixedSize(84, 56)
        self._btn_copy.setIcon(icons.icon('copy', theme.TEXT_BODY, 14))
        self._btn_copy.setIconSize(QSize(14, 14))
        self._btn_copy.setCursor(Qt.PointingHandCursor)
        self._btn_copy.clicked.connect(self._copy_code)
        code_row.addWidget(self._btn_copy)
        lay.addLayout(code_row)

        # ② 打开授权页
        lay.addWidget(_label('② 打开授权页面，粘贴上面的码', theme.TEXT_MUTED,
                             theme.FS_TINY, 600))

        self._btn_open = QPushButton('  打开 GitHub 授权页面')
        self._btn_open.setObjectName('PrimaryButton')
        self._btn_open.setFixedHeight(38)
        self._btn_open.setIcon(icons.icon('external', '#FFFFFF', 14))
        self._btn_open.setIconSize(QSize(14, 14))
        self._btn_open.setCursor(Qt.PointingHandCursor)
        self._btn_open.clicked.connect(self._open_browser)
        lay.addWidget(self._btn_open)

        # 状态行
        status = QHBoxLayout()
        status.setSpacing(8)
        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(
            f'background: {theme.WARNING}; border-radius: 4px;')
        status.addWidget(self._dot)

        self._status = _label('正在申请验证码…', theme.TEXT_SECOND, theme.FS_SMALL)
        status.addWidget(self._status)
        status.addStretch(1)

        self._count = _label('', theme.TEXT_FAINT, theme.FS_LABEL, mono=True)
        status.addWidget(self._count)
        lay.addLayout(status)

        lay.addWidget(self._build_error())

        note = _label('授权范围：读写你的仓库（repo）、读取账号信息（read:user）。'
                      '随时可以在 GitHub 的 Settings → Applications 里撤销。',
                      theme.TEXT_FAINT, theme.FS_TINY)
        note.setWordWrap(True)
        lay.addWidget(note)
        return body

    def _build_error(self) -> QFrame:
        box = QFrame()
        box.setObjectName('AuthError')
        box.setVisible(False)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 11, 12, 11)
        lay.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(9)
        icon = QLabel()
        icon.setPixmap(icons.icon('alert-circle', theme.ERROR, 15).pixmap(15, 15))
        icon.setFixedSize(15, 15)
        top.addWidget(icon, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self._err_title = _label('', theme.ERROR, theme.FS_SMALL, 600)
        self._err_title.setWordWrap(True)
        text_col.addWidget(self._err_title)

        self._err_hint = _label('', theme.TEXT_SECOND, theme.FS_SMALL)
        self._err_hint.setWordWrap(True)
        self._err_hint.setVisible(False)
        text_col.addWidget(self._err_hint)
        top.addLayout(text_col, 1)
        lay.addLayout(top)

        self._btn_detail = QToolButton()
        self._btn_detail.setObjectName('LinkButton')
        self._btn_detail.setText('查看技术详情')
        self._btn_detail.setCursor(Qt.PointingHandCursor)
        self._btn_detail.setAutoRaise(True)
        self._btn_detail.clicked.connect(self._toggle_detail)
        self._btn_detail.setVisible(False)
        lay.addWidget(self._btn_detail)

        self._err_detail = _label('', theme.TEXT_FAINT, theme.FS_LABEL, mono=True)
        self._err_detail.setWordWrap(True)
        self._err_detail.setVisible(False)
        lay.addWidget(self._err_detail)

        self._error_box = box
        return box

    def _build_footer(self) -> QFrame:
        foot = QFrame()
        lay = QHBoxLayout(foot)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(10)
        lay.addStretch(1)

        self._btn_cancel = QPushButton('取消')
        self._btn_cancel.setObjectName('DialogButton')
        self._btn_cancel.setFixedSize(76, 34)
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.clicked.connect(self.reject)
        lay.addWidget(self._btn_cancel)

        # 只在失败态出现。文案已多次提到「点重试」，没有这个按钮就是言行不一
        self._btn_retry = QPushButton('  重试')
        self._btn_retry.setObjectName('PrimaryButton')
        self._btn_retry.setFixedSize(90, 34)
        self._btn_retry.setIcon(icons.icon('refresh', '#FFFFFF', 13))
        self._btn_retry.setIconSize(QSize(13, 13))
        self._btn_retry.setCursor(Qt.PointingHandCursor)
        self._btn_retry.clicked.connect(self._start_worker)
        self._btn_retry.setVisible(False)
        lay.addWidget(self._btn_retry)
        return foot

    # ───────────────────────── 状态 ─────────────────────────

    def _apply_state(self, state: str) -> None:
        """``starting`` | ``waiting`` | ``error``"""
        if state == 'starting':
            self._dot.setStyleSheet(f'background: {theme.WARNING}; border-radius: 4px;')
            self._status.setText('正在申请验证码…')
            self._status.setStyleSheet(
                f'color: {theme.TEXT_SECOND}; font-size: {theme.FS_SMALL}px;')
            self._count.setText('')
            self._btn_copy.setEnabled(False)
            self._btn_open.setEnabled(False)
            self._error_box.setVisible(False)
            self._btn_cancel.setText('取消')
            self._btn_retry.setVisible(False)

        elif state == 'waiting':
            self._dot.setStyleSheet(f'background: {theme.WARNING}; border-radius: 4px;')
            self._status.setText('等待你在浏览器中完成授权…')
            self._status.setStyleSheet(
                f'color: {theme.TEXT_SECOND}; font-size: {theme.FS_SMALL}px;')
            self._btn_copy.setEnabled(True)
            self._btn_open.setEnabled(True)
            self._error_box.setVisible(False)
            self._btn_cancel.setText('取消')
            self._btn_retry.setVisible(False)

        else:  # error
            self._dot.setStyleSheet(f'background: {theme.ERROR}; border-radius: 4px;')
            self._status.setText('授权没有完成')
            self._status.setStyleSheet(
                f'color: {theme.ERROR}; font-size: {theme.FS_SMALL}px;')
            self._count.setText('')
            self._btn_copy.setEnabled(False)
            self._btn_open.setEnabled(False)
            self._error_box.setVisible(True)
            self._btn_cancel.setText('关闭')
            self._btn_retry.setVisible(True)

    def _show_error(self, kind: str, message: str, detail: str = '') -> None:
        title, hint = _ERROR_TEXT.get(kind, (message, ''))
        self._err_title.setText(title or message)
        self._err_hint.setText(hint)
        self._err_hint.setVisible(bool(hint))
        self._err_detail.setText(detail)
        self._err_detail.setVisible(False)
        self._btn_detail.setText('查看技术详情')
        self._btn_detail.setVisible(bool(detail))
        self._apply_state('error')

    def _toggle_detail(self) -> None:
        show = not self._err_detail.isVisible()
        self._err_detail.setVisible(show)
        self._btn_detail.setText('收起技术详情' if show else '查看技术详情')
        self.adjustSize()

    # ───────────────────────── 流程 ─────────────────────────

    def start(self) -> None:
        """开始申请验证码。对话框显示时由调用方触发。"""
        self._start_worker()

    def _start_worker(self) -> None:
        # 重试时把上一轮的线程收掉（正常情况它已经结束，这一步只防万一）
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

        self._device = None
        self._code.setText('— — — — — — — —')
        self._remaining = 0.0
        self._apply_state('starting')

        worker = _AuthWorker()
        worker.code_ready.connect(self._on_code)
        worker.pending.connect(self._on_pending)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        _LIVE_WORKERS.add(worker)
        worker.finished.connect(lambda w=worker: _LIVE_WORKERS.discard(w))
        self._worker = worker
        worker.start()

    def _on_code(self, device: ghauth.DeviceCode) -> None:
        self._device = device
        self._code.setText(device.user_code)
        self._remaining = float(device.expires_in)
        self._apply_state('waiting')
        self._update_count()
        self._countdown.start()
        self.adjustSize()

    def _on_pending(self, remaining: float) -> None:
        self._remaining = remaining
        self._update_count()

    def _update_count(self) -> None:
        left = max(0.0, self._remaining)
        self._count.setText(f'还剩 {int(left // 60):d}:{int(left % 60):02d}')

    def _tick(self) -> None:
        if self._remaining > 0:
            self._remaining = max(0.0, self._remaining - 0.5)
            self._update_count()

    def _on_succeeded(self, token, acc) -> None:
        self._countdown.stop()
        self.account = account_mod.bind(acc, token.access_token)
        self.persisted = self.account.persisted
        self.accept()

    def _on_failed(self, exc: ghauth.AuthError) -> None:
        self._countdown.stop()
        self._show_error(exc.kind, exc.message, exc.detail)
        self.adjustSize()

    # ───────────────────────── 交互 ─────────────────────────

    def _copy_code(self) -> None:
        if not self._device:
            return
        QGuiApplication.clipboard().setText(self._device.user_code)
        self._btn_copy.setText(' 已复制')
        QTimer.singleShot(1600, lambda: self._btn_copy.setText(' 复制'))

    def _open_browser(self) -> None:
        if not self._device:
            return
        # 优先用带码的链接：用户打开后码已经填好，少一步手打
        url = self._device.verification_uri_complete or self._device.verification_uri
        QDesktopServices.openUrl(QUrl(url))

    def _cancel_worker(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._countdown.stop()

    def reject(self) -> None:
        self._cancel_worker()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel_worker()
        super().closeEvent(event)

    # 无边框窗口：按住空白处可以拖动
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
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
