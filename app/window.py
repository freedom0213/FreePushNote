# -*- coding: utf-8 -*-
"""主窗口：组装标题栏 / 工具栏 / 三栏主体 / 状态栏，并接上文件操作。

窗口用无边框 + 自绘标题栏，才能拿到 11px 圆角和一体化的深色；代价是要自己
实现边缘拖拽缩放（``startSystemResize``）。

本阶段范围（阶段 1）：**一个能用的纯文本编辑器**——
打开 / 编辑 / 保存 / 自动保存 / 编码与换行符提示 / 最近打开列表。
GitHub 的绑定与推送在阶段 2 接入，目前 Push 会给出明确提示而不是静默失败。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

# ── Windows 专用：让系统自己回答「这个点在窗口的哪个部位」 ──
#
# 之前的做法是在 Qt 层算边缘、再调 `startSystemResize()`。那套在实机上不灵：
# 光标会变（说明事件确实到了主窗口），但按住拖动毫无反应。
#
# 换成 `WM_NCHITTEST` 之后，命中测试由 Windows 亲自做：
#   * 光标形状由系统给（四角八边全都准）
#   * 拖拽缩放由系统接管（跟手、能贴边、不依赖 Qt 的事件传递路径）
#   * **不受子控件遮挡影响** —— 系统问的是窗口本身，不是窗口里的哪个控件
#
# 这是无边框窗口在 Windows 上最靠谱的做法。
_IS_WINDOWS = sys.platform == 'win32'
if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _WM_NCHITTEST = 0x0084
    _HTLEFT, _HTRIGHT, _HTTOP, _HTTOPLEFT, _HTTOPRIGHT = 10, 11, 12, 13, 14
    _HTBOTTOM, _HTBOTTOMLEFT, _HTBOTTOMRIGHT = 15, 16, 17

from core import config as core_config
from core import gitops, pipeline

from . import account as account_mod, fileio, icons, theme
from .widgets.accountdialog import AccountDialog
from .widgets.authdialog import GitHubAuthDialog
from .widgets.diffdialog import DiffDialog
from .widgets.editor import CodeEditor
from .widgets.findbar import FindBar
from .widgets.managedialog import ManageFolderDialog
from .widgets.notice import ask, notice
from .widgets.pulldialog import PullDialog
from .widgets.pushdialog import PushDialog
from .workers import (ApplyPullWorker, PullPlanWorker, PushWorker,
                      RemoteCheckWorker, StageWorker, start_worker)
from .widgets.panel import PanelRail, PushPanel
from .widgets.sidebar import Sidebar, SidebarRail
from .widgets.statusbar import StatusBar
from .widgets.titlebar import TitleBar
from .widgets.toolbar import EditorToolBar

RECENT_PATH = core_config.CONFIG_DIR / 'recent.json'
UI_STATE_PATH = core_config.CONFIG_DIR / 'ui.json'
RECENT_MAX = 12


def _relative_time(ts: int) -> str:
    """Unix 时间戳 → 「刚刚 / 3 分钟前 / 2 小时前」这类相对时间。"""
    if not ts:
        return ''
    delta = max(0, int(time.time()) - int(ts))
    if delta < 60:
        return '刚刚'
    if delta < 3600:
        return f'{delta // 60} 分钟前'
    if delta < 86400:
        return f'{delta // 3600} 小时前'
    if delta < 86400 * 30:
        return f'{delta // 86400} 天前'
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


def _file_stamp(p: Path) -> tuple[int, int] | None:
    """文件的 (mtime, size)。拿不到返回 None。"""
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _refs_stamp(ws: Path) -> tuple | None:
    """工作区的「git 历史有没有变」指纹。

    只读文件属性、**不起进程** —— 这正是它存在的理由：判断历史变没变
    不该再花一次 subprocess。每次 commit / push 都会重写
    ``refs/heads/<branch>``，所以它的 mtime 是最省事的失效信号。

    仓库还没建、或者引用被打包进 ``packed-refs`` 而 refs/heads 为空时返回
    None，表示「拿不到可靠指纹」—— 这时**不缓存**，宁可多读一次，
    也不能把过期的「最近推送」摆在界面上。
    """
    git_dir = ws / '.git'
    if not git_dir.is_dir():
        return None
    heads = git_dir / 'refs' / 'heads'
    ref_files = sorted(p for p in heads.glob('*') if p.is_file()) if heads.is_dir() else []
    if not ref_files:
        return None
    parts = []
    for p in ref_files:
        stamp = _file_stamp(p)
        if stamp:
            parts.append((p.name, stamp))
    for rel in ('HEAD', 'packed-refs'):
        stamp = _file_stamp(git_dir / rel)
        if stamp:
            parts.append((rel, stamp))
    return tuple(parts) or None


class _EmptyState(QWidget):
    """编辑区空态：没有打开文件时给一句引导，而不是留一块空白。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addStretch(1)

        icon = QLabel()
        icon.setPixmap(icons.icon('doc-file', theme.TEXT_GHOST, 40).pixmap(40, 40))
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        title = QLabel('打开一个 txt 开始写作')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: 14px;')
        lay.addWidget(title)

        hint = QLabel('Ctrl + O 打开文件，或直接把文件拖进窗口')
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f'color: {theme.TEXT_FAINT}; font-size: {theme.FS_SMALL}px;')
        lay.addWidget(hint)

        lay.addStretch(1)


class FreePushWindow(QWidget):
    # 判定为「窗口边缘」的宽度。8px 比 Windows 默认的 4px 宽一倍 ——
    # 无边框窗口没有系统边框做视觉提示，太窄了根本瞄不准。
    RESIZE_MARGIN = 8

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('FreePushNote')
        self.setWindowIcon(icons.app_icon())
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Windows 走 WM_NCHITTEST，不需要预留可拖拽边；其他平台靠这圈边距让 Qt 收到事件
        self._inset = 0 if _IS_WINDOWS else self.RESIZE_MARGIN

        self.setMinimumSize(theme.WIN_MIN_W, theme.WIN_MIN_H)
        self.resize(theme.WIN_W + 2 * self._inset, theme.WIN_H + 2 * self._inset)
        self.setAcceptDrops(True)
        # 非 Windows 时靠它拿到「不按键掠过」的 mouseMoveEvent
        self.setMouseTracking(True)

        # 运行态
        self._current: Path | None = None
        self._encoding = 'utf-8'
        self._eol = 'crlf'
        self._dirty = False
        self._recent: list[str] = self._load_recent()
        # 已绑定的 GitHub 账号。「账号信息 + 令牌」两者都在才算，见 app/account.py
        self._account = account_mod.session()
        # 绑定配置（分组 / 仓库）的内存副本；界面要频繁读它，不必每次读盘
        try:
            self._cfg = core_config.load()
            self._cfg_error = ''
        except core_config.ConfigError as exc:
            self._cfg = core_config.blank_config()
            self._cfg_error = str(exc)
        self._push_busy = False
        # 推送过程的输出。界面上不展示（用户不关心 git 命令），
        # 但失败时放进「详细信息」里，排查问题全靠它。
        self._push_log_lines: list[str] = []
        # 这次推送 / 拉取对应的分组（整理在后台线程里跑，确认层要用回同一个分组）
        self._push_group: dict | None = None
        self._pull_group: dict | None = None
        #: 当前忙的是什么：'push' | 'pull' | None —— 界面文案要跟着变
        self._busy_kind: str | None = None

        # Windows 无边框窗口的「点任务栏最小化」只允许修一次（见 showEvent）
        self._taskbar_fixed = False

        # ── 缓存 ──
        # 切文件、点鼠标、改一个字都会走到刷新；不缓存就等于每操作一下
        # 都去读盘或起一个 git 进程 —— 表现就是「点了没反应，然后卡一下才动」。
        # 每个缓存的失效键都写在对应读取处。
        self._cfg_stamp: tuple | None = None          # config.json 的 (mtime, size)
        self._groups_sig: str | None = None           # 左栏「受管理的文件夹」内容指纹
        self._hist_cache: dict[str, tuple] = {}       # 工作区 → (refs 指纹, 提交列表)
        self._pushed_cache: dict[str, tuple] = {}     # (分组, 文件名) → (文件指纹, 结论)

        self._build_ui()
        self._build_shortcuts()

        # 自动保存：输入停下来 800ms 才落盘，避免每敲一个字就写磁盘
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(800)
        self._autosave.timeout.connect(self._do_autosave)

        self.sidebar.set_recent(self._recent)
        self._restore_ui_state()
        self._refresh_all()

    # ───────────────────────── 界面组装 ─────────────────────────

    def _build_ui(self) -> None:
        # 四周留一圈 RESIZE_MARGIN 的透明区，专门用来拖拽缩放。
        # 不留的话，这一圈会被内容容器完全盖住，主窗口收不到任何鼠标事件 ——
        # 这就是上一版「鼠标移到边缘拖不动」的根因。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(*([self._inset] * 4))

        self._root = QFrame()
        self._root.setObjectName('Root')
        self._outer.addWidget(self._root)

        inner = QVBoxLayout(self._root)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        self.titlebar = TitleBar(self)
        inner.addWidget(self.titlebar)

        self.toolbar = EditorToolBar()
        self.toolbar.new_requested.connect(self.new_file)
        self.toolbar.open_requested.connect(lambda: self.open_file())
        self.toolbar.save_requested.connect(self.save_file)
        self.toolbar.find_requested.connect(self.find_in_file)
        self.toolbar.settings_requested.connect(self.open_settings)
        inner.addWidget(self.toolbar)

        # ── 中段三栏 ──
        center = QWidget()
        center_lay = QHBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.file_activated.connect(self.load_path)
        self.sidebar.managed_file_activated.connect(self.load_path)
        self.sidebar.new_note_requested.connect(self.new_file)
        self.sidebar.collapse_requested.connect(self.toggle_sidebar)
        self.sidebar.context_requested.connect(self._show_file_menu)
        self.sidebar.recent_removed.connect(self._remove_recent)
        center_lay.addWidget(self.sidebar)

        # 左栏收起后的窄条：一个按钮就地展开，不用跑去工具栏找
        self.sidebar_rail = SidebarRail()
        self.sidebar_rail.setVisible(False)
        self.sidebar_rail.expand_requested.connect(self.toggle_sidebar)
        center_lay.addWidget(self.sidebar_rail)

        self.editor = CodeEditor()
        self.editor.content_changed.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._update_cursor)
        self.editor.font_size_changed.connect(self._on_font_size_changed)

        self._editor_stack = QStackedWidget()
        self._editor_stack.addWidget(_EmptyState())
        self._editor_stack.addWidget(self.editor)

        # 编辑区 = 查找条 + 编辑器。查找条平时藏着，Ctrl+F 才落下来 ——
        # 它属于编辑区（找的是这一篇里的词），不占工具栏的位置。
        #
        # ⚠️ 顺序即位置：这里 addWidget 的先后决定了三栏的左右关系。
        # 编辑器**只能**被加一次 —— 之前它先被中段布局收走、又被这里收进
        # 查找条容器，Qt 会把它从旧布局摘掉，结果整个编辑区被排到了推送面板
        # 右边（左栏 → 右栏 → 编辑区），界面上一眼就能看出不对。
        self._findbar = FindBar(self.editor)
        self._findbar.setVisible(False)
        self._findbar.close_requested.connect(self._close_findbar)

        editor_area = QWidget()
        editor_lay = QVBoxLayout(editor_area)
        editor_lay.setContentsMargins(0, 0, 0, 0)
        editor_lay.setSpacing(0)
        editor_lay.addWidget(self._findbar)
        editor_lay.addWidget(self._editor_stack, 1)
        center_lay.addWidget(editor_area, 1)

        self.panel = PushPanel()
        self.panel.collapse_requested.connect(lambda: self.toggle_panel(False))
        self.panel.push_requested.connect(self.on_push)
        self.panel.pull_requested.connect(self.on_pull)
        self.panel.diff_requested.connect(self.on_diff)
        self.panel.settings_requested.connect(self.open_settings)
        self.panel.account_chip_clicked.connect(self.open_account)
        center_lay.addWidget(self.panel)

        self.rail = PanelRail()
        self.rail.setVisible(False)
        self.rail.expand_requested.connect(lambda: self.toggle_panel(True))
        self.rail.push_requested.connect(self.on_push)
        self.rail.settings_requested.connect(self.open_settings)
        center_lay.addWidget(self.rail)

        inner.addWidget(center, 1)

        self.statusbar = StatusBar()
        inner.addWidget(self.statusbar)

    def _build_shortcuts(self) -> None:
        def bind(seq: str, slot) -> None:
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.activated.connect(slot)

        bind('Ctrl+N', self.new_file)
        bind('Ctrl+O', lambda: self.open_file())
        bind('Ctrl+S', self.save_file)
        bind('Ctrl+Shift+S', self.save_file_as)
        bind('Ctrl+F', self.find_in_file)
        bind('Ctrl+Enter', self.on_push)
        bind('Ctrl+,', self.open_settings)
        bind('Ctrl+B', self.toggle_sidebar)
        # 字号：Ctrl+滚轮是主入口，键盘也留一套（有些鼠标没有滚轮方向键）
        for seq in ('Ctrl+=', 'Ctrl++'):
            bind(seq, self._zoom_in)
        for seq in ('Ctrl+-', 'Ctrl+_'):
            bind(seq, self._zoom_out)
        bind('Ctrl+0', self._reset_zoom)

    # ───────────────────────── 文件操作 ─────────────────────────

    def new_file(self) -> None:
        self._current = None
        self._encoding = 'utf-8'
        self._eol = 'crlf'
        self._dirty = False
        self.editor.load_text('')
        self._editor_stack.setCurrentIndex(1)
        self.editor.setFocus()
        self._refresh_all()

    def load_path(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            notice(self, '文件不存在', f'找不到这个文件：\n\n{p}', kind='warning')
            self._remove_recent(str(p))
            return
        try:
            text, enc, eol = fileio.read_text(p)
        except OSError as exc:
            notice(self, '打不开这个文件', f'{p}\n\n{exc}', kind='error')
            return

        self._current = p
        self._encoding = enc
        self._eol = eol
        self.editor.load_text(text)
        self._editor_stack.setCurrentIndex(1)
        self._dirty = False
        self._touch_recent(str(p))
        self.editor.setFocus()
        self._refresh_all()

    def open_file(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, '打开文本文件', str(Path.home()),
                '文本文件 (*.txt);;Markdown (*.md);;所有文件 (*)')
        if path:
            self.load_path(path)

    def save_file(self) -> bool:
        if self._current is None:
            return self.save_file_as()
        try:
            fileio.write_text(self._current, self.editor.toPlainText(),
                              self._encoding, self._eol)
        except OSError as exc:
            notice(self, '保存失败', f'{self._current}\n\n{exc}', kind='error')
            return False
        self._dirty = False
        # 存过了 → 它才算真正「最近用过」，这时才值得排到第一位。
        # 自动保存也走这里：用户敲了字本身就是「在这篇上干活」的证据，
        # 不区分是 Ctrl+S 还是防抖落盘。
        self._promote_recent(str(self._current))
        self._refresh_title()
        return True

    def save_file_as(self) -> bool:
        suggested = str(self._current) if self._current else str(Path.home() / '未命名.txt')
        path, _ = QFileDialog.getSaveFileName(
            self, '另存为', suggested, '文本文件 (*.txt);;所有文件 (*)')
        if not path:
            return False
        self._current = Path(path)
        if self.save_file():
            self._promote_recent(path)
            self._refresh_all()
            return True
        return False

    def _do_autosave(self) -> None:
        """自动保存：只覆盖已有文件，不弹「另存为」——没人希望打字打到一半跳对话框。"""
        if self._dirty and self._current is not None:
            self.save_file()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._dirty and self._current is not None:
            if not self.save_file():
                event.ignore()
                return
        self._save_recent()
        self._save_ui_state()
        super().closeEvent(event)

    # ───────────────────────── 最近打开 ─────────────────────────

    def _load_recent(self) -> list[str]:
        try:
            data = json.loads(RECENT_PATH.read_text(encoding='utf-8'))
            items = data.get('recent') or []
            return [str(p) for p in items][:RECENT_MAX]
        except (OSError, ValueError, AttributeError):
            return []

    def _save_recent(self) -> None:
        try:
            RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            RECENT_PATH.write_text(
                json.dumps({'recent': self._recent}, ensure_ascii=False, indent=2),
                encoding='utf-8', newline='\n')
        except OSError:
            pass

    def _touch_recent(self, path: str) -> None:
        """打开文件时把它记进列表，**但不改变已有顺序**。

        排序规则是用户定的：翻看笔记不算「用过」，只有保存过才把它提到第一位。
        否则「随手点开几篇看看」就会把顺序搅乱，而这个列表的价值恰恰在于顺序稳定。
        新出现的文件追加在末尾 —— 不抢占位置。
        """
        if path in self._recent:
            return
        self._recent.append(path)
        del self._recent[RECENT_MAX:]
        self._save_recent()
        self.sidebar.set_recent(self._recent)

    def _promote_recent(self, path: str) -> None:
        """保存成功 → 把它提到第一位。这才是「我在这篇上干过活」的证据。"""
        if self._recent and self._recent[0] == path:
            return
        if path in self._recent:
            self._recent.remove(path)
        self._recent.insert(0, path)
        del self._recent[RECENT_MAX:]
        self._save_recent()
        self.sidebar.set_recent(self._recent)

    def _remove_recent(self, path: str) -> None:
        """把一条从「最近打开」里移除。

        **不关掉正在编辑的文档** —— 用户的意图是「别老在这儿占地方」，
        不是「我不想再编辑这个文件了」。真要关，他自己会关。
        """
        if path not in self._recent:
            return
        self._recent.remove(path)
        self._save_recent()
        self.sidebar.set_recent(self._recent)
        self.sidebar.highlight_recent(str(self._current) if self._current else None)

    # ───────────────────────── 状态刷新 ─────────────────────────

    def _on_text_changed(self) -> None:
        self._dirty = True
        self._refresh_title()
        self._update_cursor()
        self._refresh_sync()
        if self._current is not None:
            self._autosave.start()

    def _update_cursor(self) -> None:
        line, col = self.editor.line_col()
        self.statusbar.set_cursor(line, col)
        lines, chars = self.editor.stats()
        self.statusbar.set_stats(lines, chars)

    def _refresh_title(self) -> None:
        name = self._current.name if self._current else None
        self.titlebar.set_file_name(name, self._dirty)

    def _refresh_encoding(self) -> None:
        # 非 UTF-8 一律标黄：推到 GitHub 会乱码
        enc_name = fileio.DISPLAY_NAME.get(self._encoding, self._encoding)
        self.statusbar.set_encoding(enc_name, warn=self._encoding != 'utf-8')
        self.statusbar.set_eol(fileio.EOL_DISPLAY.get(self._eol, self._eol).upper(),
                               warn=self._eol == 'crlf')

    def _apply_sync(self, state: str, *, push: str = 'ready',
                    text: str | None = None, icon: str | None = None,
                    desc: str | None = None) -> None:
        """把同步状态一次性刷到四处：右栏卡片 / Push 按钮 / 状态栏 / 窄条。

        这四处必须一致 —— 只改其中一处，界面就会自己打自己的脸
        （状态卡片写着「已同步」，状态栏还写着「待 push」）。
        """
        if desc is None:
            self.panel.set_sync_state(state)
        else:
            self.panel.set_sync_state(state, desc=desc)
        self.panel.set_push_state(push, text=text, icon_name=icon)
        self.statusbar.set_sync(state)
        self.rail.set_sync_state(state)

    def _refresh_sync(self) -> None:
        """按「有没有绑账号 / 有没有纳管 / 有没有改动」决定这一屏该说什么。

        「这一篇是否已推送」靠 **本地工作区的副本** 判断（见 pipeline.is_pushed）——
        不联网也能给出诚实结论，而不是凭「用户没再编辑过」去猜。
        「远端领先 / 双方分叉」需要连远端，留到下一批做。
        """
        if self._account is None:
            # 账号都没绑，谈同步没有意义 —— 直接引导授权。
            # 按钮文案跟着换成「绑定 GitHub 账号」，且**必须可点**：
            # 灰着不给任何反应是最糟的交互。
            self._apply_sync('unlinked', text='绑定 GitHub 账号', icon='github')
            return

        group = self._current_group()
        managed = bool(group) and core_config.is_managed(self._cfg, self._current)

        if self._current is None or self._editor_stack.currentIndex() != 1:
            self._apply_sync(
                'unmanaged', push='disabled',
                desc=f'已绑定 {self._account.login}。打开一个 txt 后，就能把它纳入管理。')
            return

        if self._push_busy:
            self._apply_sync('running', push='running',
                             text='正在拉取…' if self._busy_kind == 'pull' else None)
            return

        if not managed:
            # 两种未纳管：整个文件夹还没关联，或者文件夹纳管了但这一篇没勾
            if group:
                text = '关联 GitHub 仓库' if not group.get('repo') else '纳入 GitHub 管理'
                desc = f'这个文件属于分组「{group.get("name")}」，但还没被纳入管理。'
            else:
                text = '纳入 GitHub 管理'
                desc = (f'「{self._current.parent.name}」还没有关联仓库。'
                        f'点下面的按钮开始 —— 只会上传你勾选的文件。')
            self._apply_sync('unmanaged', text=text, desc=desc)
            return

        if self._dirty:
            # 有未保存的改动 = 一定有东西要推，**不必**再去读文件比对。
            # 这个短路挡掉的正是「每敲一个字读一遍源文件 + 工作区副本」的开销。
            self._apply_sync('pending')
            return

        if self._is_pushed(group) is True:
            # 已经推上去、本地也没再改 —— 按钮保持可点（万一远端落后可以重推），
            # 但视觉压成灰色，不诱导用户去点。
            self._apply_sync('synced', push='uptodate', text='已是最新，无需推送')
        else:
            self._apply_sync('pending')

    def _is_pushed(self, group: dict) -> bool | None:
        """带缓存的 :func:`pipeline.is_pushed`。

        每判断一次都要读源文件 + 工作区副本，而笔记动辄上百 KB；
        切文件、刷新状态都会走到这里，真读就意味着点一下鼠标要等一次磁盘 IO。
        用两边的 ``(mtime, size)`` 当失效键 —— 四次 stat 比读两个文件便宜得多，
        而任一文件被改过就会自动重算，不会给出过期结论。
        """
        name = self._current.name if self._current else ''
        folder = Path(str(group.get('folder') or ''))
        ws = core_config.workspace_dir(group)
        key = f'{group.get("id")}\x00{name}'
        sig = (_file_stamp(folder / name), _file_stamp(ws / name))
        cached = self._pushed_cache.get(key)
        if cached is not None and cached[0] == sig:
            return cached[1]
        result = pipeline.is_pushed(group, name)
        self._pushed_cache[key] = (sig, result)
        return result

    def _refresh_all(self) -> None:
        self._reload_cfg()
        self._refresh_title()
        self._update_cursor()
        self._refresh_encoding()
        self._refresh_groups()
        self._refresh_sync()
        self.toolbar.set_has_file(self._current is not None
                                  or self._editor_stack.currentIndex() == 1)
        self.sidebar.highlight_recent(str(self._current) if self._current else None)
        self._refresh_panel()

    def _reload_cfg(self, force: bool = False) -> None:
        """读回配置。

        文件没变就直接用内存里的副本 —— 这个函数每次刷新都会走到，
        而切文件时刷新很频繁，没必要每次都去读一趟磁盘。
        """
        stamp = _file_stamp(core_config.CONFIG_PATH)
        if not force and stamp is not None and stamp == self._cfg_stamp:
            return
        try:
            self._cfg = core_config.load()
            self._cfg_error = ''
        except core_config.ConfigError as exc:
            self._cfg = core_config.blank_config()
            self._cfg_error = str(exc)
        self._cfg_stamp = stamp

    def _refresh_groups(self) -> None:
        """把配置里的分组渲染到左栏「受管理的文件夹」。

        内容没变就**不重建控件树**：重建会把各分组的展开/折叠状态
        连同滚动位置一起抹掉，而切文件时这个函数每次都会走到。
        """
        view = []
        for g in core_config.groups(self._cfg):
            folder = Path(str(g.get('folder') or ''))
            view.append({
                'name': str(g.get('name') or folder.name),
                'repo': str(g.get('repo') or ''),
                'folder': str(folder),
                'files': [str(folder / n) for n in core_config.managed_names(g)],
            })
        sig = repr(view)
        if sig == self._groups_sig:
            return
        self._groups_sig = sig
        self.sidebar.set_managed(view)

    def _current_group(self) -> dict | None:
        if self._current is None:
            return None
        return core_config.group_for_path(self._cfg, self._current)

    def _refresh_panel(self) -> None:
        """右栏的仓库卡片 / 归属 / 最近推送 —— 全部读真实数据。"""
        self.panel.set_account(self._account.login if self._account else None)
        group = self._current_group()
        if group is None:
            self.panel.set_repo(None, None, None)
            self.statusbar.set_owner(None, None)
            self.panel.set_history([])
            return

        folder = Path(str(group.get('folder') or ''))
        name = self._current.name if self._current else ''
        self.panel.set_repo(str(group.get('repo') or ''),
                            str(group.get('branch') or 'main'),
                            f'{folder.name}/{name}',
                            group=str(group.get('name') or ''))
        self.statusbar.set_owner(str(group.get('name') or ''), str(group.get('repo') or ''))

        records = self._group_history(group)
        self.panel.set_history(records)
        if records:
            self.panel.set_last_sync(records[0]['relative'], records[0]['hash'])

    def _group_history(self, group: dict) -> list[dict]:
        """该工作区的提交列表（带缓存）。

        读它要起一个 git 子进程。切文件时右栏要重画，若不缓存，
        每点一次侧栏就白等一次子进程启动 —— 用户看到的就是
        「点了没反应，过一会儿才切过去」。
        """
        ws = core_config.workspace_dir(group)
        if not (ws / '.git').is_dir():
            return []                      # 还没推过：连 .git 都没有，不必问 git
        sig = _refs_stamp(ws)
        cached = self._hist_cache.get(str(ws))
        if sig is not None and cached is not None and cached[0] == sig:
            return cached[1]
        records = [{'hash': c['hash'], 'message': c['message'],
                    'relative': _relative_time(c['ts'])}
                   for c in gitops.recent_commits(ws, 5)]
        if sig is not None:
            self._hist_cache[str(ws)] = (sig, records)
        return records

    # ───────────────────────── 界面状态（字号 / 栏显隐） ─────────────────────────

    def _zoom_in(self) -> None:
        self.editor.set_font_size(self.editor.font_size() + 1)

    def _zoom_out(self) -> None:
        self.editor.set_font_size(self.editor.font_size() - 1)

    def _reset_zoom(self) -> None:
        self.editor.set_font_size(theme.FS_BODY)

    def _on_font_size_changed(self, _size: int) -> None:
        self._save_ui_state()

    def _restore_ui_state(self) -> None:
        """恢复上次的字号与侧栏显隐。"""
        state = self._read_ui_state()
        size = state.get('editor_font_size')
        if isinstance(size, int):
            self.editor.set_font_size(size, emit=False)
        if state.get('panel_visible') is False:
            self.toggle_panel(False)
        if state.get('sidebar_visible') is False:
            self.toggle_sidebar()

    def _read_ui_state(self) -> dict:
        try:
            data = json.loads(UI_STATE_PATH.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_ui_state(self) -> None:
        """把字号与栏显隐记住 —— 自己调舒服的字号，下次打开还得在。"""
        data = {
            'editor_font_size': self.editor.font_size(),
            'sidebar_visible': self.sidebar.isVisible(),
            'panel_visible': self.panel.isVisible(),
        }
        try:
            UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            UI_STATE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8', newline='\n')
        except OSError:
            pass

    # ───────────────────────── 视图切换 ─────────────────────────

    def toggle_sidebar(self) -> None:
        """收起 / 展开左侧栏。

        收起后**原地**留一条 40px 窄条，顶部就是展开按钮 —— 跟右侧栏同一套交互。
        能收起来就必须能再打开，否则那不叫收起，叫关掉。
        """
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        self.sidebar_rail.setVisible(not visible)
        self._save_ui_state()

    def toggle_panel(self, show: bool) -> None:
        self.panel.setVisible(show)
        self.rail.setVisible(not show)
        self._save_ui_state()

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _apply_resize_margins(self) -> None:
        """最大化 / 全屏时不留那圈透明边，否则内容会凭空缩进一圈。

        Windows 上 ``_inset`` 恒为 0 —— 命中测试交给系统，不需要预留可拖拽区。
        """
        m = 0 if (self.isMaximized() or self.isFullScreen()) else self._inset
        self._outer.setContentsMargins(m, m, m, m)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange:
            maximized = self.isMaximized()
            self._apply_resize_margins()
            self._root.setProperty('maximized', 'true' if maximized else 'false')
            self._root.style().unpolish(self._root)
            self._root.style().polish(self._root)
            self.titlebar.set_maximized(maximized)
        super().changeEvent(event)

    # ───────────────────────── 尚未接入的动作 ─────────────────────────

    def on_push(self) -> None:
        """Push 按钮的全部分支都收在这里 —— 它同时是「下一步该做什么」的入口。

        三种情况分别导向：先绑账号 / 先纳管 / 真的推送。用户只管点同一个按钮。
        """
        if self._push_busy:
            return
        if self._account is None:
            self.bind_github_account()
            return
        if self._current is None or self._editor_stack.currentIndex() != 1:
            return

        group = self._current_group()
        if (group is None
                or not group.get('repo')
                or not core_config.is_managed(self._cfg, self._current)):
            group = self.manage_current_folder(existing=group)
            if group is None:
                return
        self.do_push(group)

    # ───────────────────────── 纳管与推送 ─────────────────────────

    def manage_current_folder(self, existing: dict | None = None) -> dict | None:
        """打开纳管对话框；确认后落库并刷新。返回最终的分组字典。"""
        if self._current is None:
            return None
        return self.manage_folder_for(self._current, existing=existing)

    def manage_folder_for(self, path: Path, existing: dict | None = None) -> dict | None:
        """对某个文件所在的文件夹走纳管流程（右键菜单也会用到）。"""
        preselect = list(core_config.managed_names(existing)) if existing else []
        if path.name not in preselect:
            preselect.append(path.name)

        dlg = ManageFolderDialog(path.parent, preselect=preselect,
                                 existing=existing, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.group is None:
            return None

        self._reload_cfg()
        core_config.upsert_group(self._cfg, dlg.group)
        try:
            core_config.save(self._cfg)
        except OSError as exc:
            notice(self, '没能保存配置',
                   f'绑定的信息写不进配置文件：\n\n{exc}', kind='error')
            return None
        self._refresh_all()
        return dlg.group

    def do_push(self, group: dict) -> None:
        """推送分三步走：**先看远端** → 本地整理 → 用户确认 → 提交并推送。

        第一步（检查远端）是这一版新加的：如果远端已经有本地没有的提交，
        直接推会被 GitHub 以「非快进」拒绝 —— 那个报错对写笔记的人来说
        完全读不懂。不如提前发现，把用户引到「先拉取」这条正确的路上。

        后两步都要后台跑：整理要起十来个 git 进程、读写成堆文件，
        放在界面线程上就是「点了 Push 之后整窗僵住两三秒」。
        """
        if self._push_busy:
            return
        self._push_log_lines = []
        self._push_busy = True
        self._busy_kind = 'push'
        self._push_group = group          # 异步链路要一路用回同一个分组
        self._refresh_sync()
        self.panel.set_progress('checking')
        token = self._account.token if self._account else ''
        worker = RemoteCheckWorker(group, token=token, on_log=self._push_log)
        worker.done.connect(self._on_remote_checked)
        start_worker(worker)

    def _on_remote_checked(self, info: dict) -> None:
        """远端看完了：远端领先就先拉取，否则继续整理。

        检查失败（``info['ok']`` 为假，例如没网）**不拦人** —— 那只是没查成，
        不是「远端有新东西」；真正的失败留给 push 那一步去报。
        """
        group = self._push_group
        if not group:
            self._push_busy = False
            self._busy_kind = None
            self.panel.set_progress(None)
            return

        behind = int(info.get('behind', 0) or 0)
        if info.get('ok') and behind > 0:
            self._push_busy = False
            self._busy_kind = None
            self.panel.set_progress(None)
            self._refresh_all()
            if ask(self, '远端有新的改动',
                   f'GitHub 上已经有 {behind} 个提交是本地没有的。\n\n'
                   '直接推送会被 GitHub 拒绝 —— 它不允许覆盖别处的改动。'
                   '先把远端的内容拉下来，再推送。',
                   ok_text='现在拉取', cancel_text='稍后再说', kind='warning'):
                self.on_pull()
            return

        self.panel.set_progress('preparing')
        worker = StageWorker(group, account=account_mod.info(),
                             on_log=self._push_log)
        worker.done.connect(self._on_stage_done)
        start_worker(worker)

    def _on_stage_done(self, staged) -> None:
        """整理完成：要么直接失败，要么弹确认层让用户过目这次要推什么。"""
        self._push_busy = False
        self.panel.set_progress(None)

        if not staged.ok:
            self._push_failed(staged.message, staged.detail, staged.warnings)
            return
        if not staged.has_changes:
            self._refresh_all()
            # 文案写死在这里，**不要**用 staged.message ——
            # 整理成功但没有变更时，那个字段是空的（stage_group 只在失败分支
            # 填它），照搬过来就是一个只有图标和 OK 的空框，等于什么也没说。
            notice(self, '无需推送',
                   '本地内容与 GitHub 上的一致，没有需要推送的改动。',
                   kind='info')
            return

        group = self._push_group or self._current_group() or {}
        dlg = PushDialog(group, staged, self)
        if dlg.exec() != QDialog.Accepted:
            self._refresh_all()
            return

        token = self._account.token if self._account else ''
        self._push_busy = True
        self._refresh_sync()
        self.panel.set_progress('pushing')
        worker = PushWorker(group, staged, message=dlg.message, keep=dlg.keep,
                            token=token)
        worker.done.connect(self._on_push_done)
        start_worker(worker)

    def _push_log(self, text: str) -> None:
        self._push_log_lines.append(str(text))
        del self._push_log_lines[:-200]

    def _on_push_done(self, result) -> None:
        self._push_busy = False
        self.panel.set_progress(None)
        self._refresh_all()

        if result.ok:
            # 成功：按钮先亮成绿色，停一下再回落到「已是最新」
            self.panel.set_push_state('success', text=f'已推送 {result.commit}')
            QTimer.singleShot(1800, self._refresh_all)
            if result.warnings:
                notice(self, '推送完成（有提醒）',
                       result.message + '\n\n'
                       + '\n'.join(f'· {w}' for w in result.warnings),
                       kind='warning')
            return

        self._push_failed(result.message, result.detail, result.warnings)

    def _push_failed(self, message: str, detail: str = '',
                     warnings: list[str] | None = None) -> None:
        self._push_busy = False
        self.panel.set_progress(None)
        self._refresh_all()
        self.panel.set_sync_state('failed', desc=message)
        self.panel.set_push_state('failed')
        self.statusbar.set_sync('failed')
        self.rail.set_sync_state('failed')

        text = message
        if warnings:
            text += '\n\n' + '\n'.join(f'· {w}' for w in warnings)
        notice(self, '推送失败',
               text + '\n\n改动已保存在本地，不会丢失。修好后可以直接重试。',
               kind='error',
               detail=detail or '\n'.join(self._push_log_lines[-40:]))

    # ───────────────────────── GitHub 账号绑定 ─────────────────────────

    def bind_github_account(self) -> None:
        """打开授权对话框。成功后立刻刷新界面，让用户看得见状态变了。"""
        dlg = GitHubAuthDialog(self)
        self._center_dialog(dlg)
        dlg.start()                       # 先发起申请，用户看到码的时间就更短
        accepted = dlg.exec() == QDialog.Accepted
        if not accepted or dlg.account is None:
            return

        self._account = dlg.account
        self._refresh_all()

        if not dlg.persisted:
            # 令牌没存下来就别说「已绑定」——否则下次启动用户会发现白绑了
            notice(self, '令牌没能保存到本机',
                   f'{self._account.display} 授权成功了，但令牌写入本机凭据目录失败。\n\n'
                   '这次会话内可以正常使用；下次启动需要重新授权。\n\n'
                   f'凭据目录：{core_config.CONFIG_DIR / "credentials"}',
                   kind='warning')
        else:
            notice(self, '已绑定 GitHub 账号',
                   f'{self._account.display} 已连接。\n\n'
                   '接下来打开一个 txt，点右侧的「纳入 GitHub 管理」，'
                   '就能把它关联到仓库并推送。',
                   kind='success')

    def _center_dialog(self, dlg: QDialog) -> None:
        """把对话框摆在主窗口中间（无边框窗口不会自动居中）。"""
        dlg.adjustSize()
        geo = self.geometry()
        dlg.move(geo.x() + (geo.width() - dlg.width()) // 2,
                 geo.y() + (geo.height() - dlg.height()) // 2)

    def open_account(self) -> None:
        """账户页（N-02）。入口：右栏头部的账号胶囊。

        没绑定时胶囊根本不显示，所以走到这里的账号一定存在 —— 但防御一下
        也无妨，万一刷新时序出问题，别让用户点了个寂寞。
        """
        if self._account is None:
            self.bind_github_account()
            return
        groups = [{'name': str(g.get('name') or ''),
                   'repo': str(g.get('repo') or '')}
                  for g in core_config.groups(self._cfg)]
        dlg = AccountDialog(self._account, groups, parent=self)
        self._center_dialog(dlg)
        dlg.reauth_requested.connect(self.bind_github_account)
        dlg.signed_out.connect(self._on_signed_out)
        dlg.exec()

    def _on_signed_out(self) -> None:
        """退出登录：只清凭据与账号信息（app.account.unbind），分组配置原样保留。

        界面上所有依赖账号的地方统一走 _refresh_all —— 它会把 Push 按钮
        换成「绑定 GitHub 账号」，右栏与状态栏同步回到未绑定态。
        """
        account_mod.unbind()
        self._account = None
        self._refresh_all()
        notice(self, '已退出登录',
               '本机已不再保存这个账号的令牌。\n\n'
               '笔记和仓库配置都还在，重新授权后照常推送。',
               kind='success')

    def on_pull(self) -> None:
        """把 GitHub 上的更新拉回本地笔记文件夹。

        三步，与推送同构：**分析（只算不写）→ 用户确认 → 备份后写回**。
        分析阶段不碰任何文件，所以「会更新几篇、哪篇冲突」是真实数据，
        不是先动手再报告。
        """
        if self._push_busy:
            return
        if self._account is None:
            self.bind_github_account()
            return
        group = self._current_group()
        if group is None or not group.get('repo'):
            notice(self, '还没有可拉取的仓库',
                   '这个文件所在的文件夹还没关联 GitHub 仓库，'
                   '远端也还没有它的内容。',
                   kind='info')
            return
        if not core_config.managed_names(group):
            notice(self, '没有纳入管理的文件',
                   f'分组「{group.get("name")}」里还没有勾选要同步的文件。',
                   kind='info')
            return

        # 先把编辑器里未落盘的改动写下去，再分析 ——
        # 否则分析读到的是旧磁盘内容，会把它误判成「本地没改过」而直接覆盖。
        self._do_autosave()

        self._push_log_lines = []
        self._push_busy = True
        self._busy_kind = 'pull'
        self._pull_group = group
        self._refresh_sync()
        self.panel.set_progress('pulling')
        worker = PullPlanWorker(group, token=self._account.token,
                                on_log=self._push_log)
        worker.done.connect(self._on_pull_plan)
        start_worker(worker)

    def _on_pull_plan(self, plan) -> None:
        """分析回来了：没事就直接说清楚，有事就弹确认层。"""
        self._push_busy = False
        self._busy_kind = None
        self.panel.set_progress(None)
        self._refresh_all()

        if not plan.ok:
            failed = plan.reason in (pipeline.REASON_GIT_ERROR,
                                     pipeline.REASON_FETCH_FAILED)
            notice(self, '没能读取远端',
                   plan.message + (f'\n\n{plan.detail}' if plan.detail else ''),
                   kind='error' if failed else 'warning')
            return
        if plan.reason == pipeline.REASON_UP_TO_DATE:
            notice(self, '远端没有新内容', plan.message, kind='success')
            return
        if plan.reason == pipeline.REASON_LOCAL_AHEAD:
            notice(self, '本地有还没推上去的改动', plan.message, kind='warning')
            return
        if plan.reason == pipeline.REASON_ARTIFACTS_ONLY:
            # 远端确实有新提交，但改的全是自动生成的站点文件。
            # 两件事都要做：① 让用户看懂为什么本地没变化；② 仍然对齐中转区，
            # 否则推送会被「远端领先」拦住，用户就卡在来回提示里出不来。
            group = self._pull_group or self._current_group()
            if group:
                pipeline.apply_pull(group, plan, on_log=self._push_log)
            self._refresh_all()
            lines = '\n'.join(f'· {p}' for p in plan.outside[:8])
            notice(self, '远端只改了自动生成的文件',
                   f'远端有 {plan.behind} 个新提交，但它们改的是这些自动生成的文件：\n\n'
                   f'{lines}\n\n'
                   f'你的笔记原文（{"、".join(core_config.managed_names(group))}）'
                   f'没有变化，所以本地不需要写回。\n\n'
                   f'这些生成文件每次推送都会按笔记原文重新生成 —— '
                   f'换句话说，在 GitHub 网页上对它们的修改，'
                   f'会在你下次推送时被覆盖。要改内容，请改 .txt 原文。',
                   kind='warning')
            return

        group = self._pull_group or self._current_group() or {}
        dlg = PullDialog(plan, self)
        self._center_dialog(dlg)
        if dlg.exec() != QDialog.Accepted:
            return

        self._push_busy = True
        self._busy_kind = 'pull'
        self._refresh_sync()
        self.panel.set_progress('pulling')
        worker = ApplyPullWorker(group, plan, on_log=self._push_log)
        worker.done.connect(self._on_pull_done)
        start_worker(worker)

    def _on_pull_done(self, result) -> None:
        self._push_busy = False
        self._busy_kind = None
        self.panel.set_progress(None)
        self._reload_after_pull(result)
        self._refresh_all()

        if not result.ok:
            notice(self, '拉取没有完成',
                   result.message + (f'\n\n{result.detail}' if result.detail else ''),
                   kind='error',
                   detail='\n'.join(self._push_log_lines[-40:]))
            return

        body = result.message
        if result.conflicts:
            body += ('\n\n冲突的笔记保留了你本地的版本，'
                     '想看远端那份可以点「查看差异」。')
        if result.backup_dir:
            body += f'\n\n改写前的版本已备份到：{result.backup_dir}'
        notice(self, '拉取完成', body,
               kind='warning' if result.conflicts else 'success')

    def _reload_after_pull(self, result) -> None:
        """被改写的笔记如果正开在编辑器里，重新读盘。

        不做这一步，界面上显示的还是旧内容 —— 用户会以为拉取没生效，
        然后在旧内容上继续编辑、再推回去，等于把刚拉下来的改动又盖掉。
        """
        if self._current is None or self._current.name not in (result.written or []):
            return
        try:
            text, enc, eol = fileio.read_text(self._current)
        except OSError:
            return
        self._encoding, self._eol = enc, eol
        self.editor.load_text(text)
        self._dirty = False
        self._refresh_encoding()
        self._refresh_title()

    def on_diff(self) -> None:
        """查看差异：本地内容 ↔ 仓库里的版本（上次推送的结果）。

        只读、不联网 —— 从工作区的 git 历史里取旧版，跟本地现读的内容比。
        「这次会改什么」在点开之前是看不见的，这个按钮就是为这件事存在的。
        """
        group = self._current_group()
        if group is None or not group.get('repo'):
            notice(self, '还没有可比较的版本',
                   '这个文件所在的文件夹还没关联 GitHub 仓库，'
                   '仓库里没有它的历史版本。',
                   kind='info')
            return
        if not core_config.managed_names(group):
            notice(self, '没有纳入管理的文件',
                   f'分组「{group.get("name")}」里还没有勾选要推送的文件。',
                   kind='info')
            return

        rows = pipeline.diff_preview(group)
        if not rows:
            notice(self, '没有未推送的改动',
                   '本地内容与仓库里的一致，没有需要推送的改动。',
                   kind='info')
            return

        dlg = DiffDialog(rows, self)
        self._center_dialog(dlg)
        dlg.exec()

    def open_settings(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle('设置')
        dlg.setFixedSize(480, 300)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)

        title = QLabel('设置')
        title.setStyleSheet(f'color: {theme.TEXT_STRONG}; font-size: 15px; font-weight: 600;')
        lay.addWidget(title)

        body = QLabel(
            '本阶段只跑通了编辑器本体，设置项会在接入 GitHub 之后开放：\n\n'
            '· GitHub 账号（授权 / 撤销）\n'
            '· 受管理的文件夹（解除绑定）\n'
            '· 推送行为：Push 前确认提交信息 / 保存后自动推送 / 推送前检测远端改动\n\n'
            f'配置文件目录：{core_config.CONFIG_DIR}')
        body.setWordWrap(True)
        body.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: {theme.FS_UI}px;')
        lay.addWidget(body, 1)

        from PySide6.QtWidgets import QPushButton
        ok = QPushButton('知道了')
        ok.setObjectName('PushButton')
        ok.setFixedHeight(36)
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        dlg.exec()

    def find_in_file(self) -> None:
        """Ctrl+F：在当前这一篇里找词（内嵌查找条）。

        按文件名找笔记是另一件事，入口在左栏的放大镜 —— 两个入口的分工
        在设计稿 N-04 里定过。空态（没打开文件）不给反应。
        """
        if self._editor_stack.currentIndex() == 0:
            return
        self._findbar.open()

    def _close_findbar(self) -> None:
        self._findbar.hide()
        self.editor.setFocus()

    # ───────────────────────── 侧栏右键菜单 ─────────────────────────

    def _show_file_menu(self, path: str, global_pos: QPoint) -> None:
        from PySide6.QtWidgets import QMenu
        p = Path(path)
        group = core_config.group_for_path(self._cfg, p)
        managed = bool(group) and core_config.is_managed(self._cfg, p)

        menu = QMenu(self)
        act_open_dir = menu.addAction(icons.icon('folder', theme.TEXT_BODY, 13),
                                      '在资源管理器中显示')
        act_rename = menu.addAction(icons.icon('pencil', theme.TEXT_BODY, 13), '重命名')
        if managed:
            # 受管理的文件禁止改名：改动会在仓库里表现为「删旧建新」，历史断掉
            act_rename.setEnabled(False)
            act_rename.setToolTip('受 GitHub 管理的文件不能改名，改名会中断仓库中的历史记录')
        menu.addSeparator()
        act_manage = menu.addAction(
            icons.icon('minus-circle', theme.TEXT_BODY, 13) if managed
            else icons.icon('push', theme.SUCCESS, 13),
            '从管理中移除' if managed else '纳入 GitHub 管理')

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_open_dir:
            import subprocess
            subprocess.Popen(['explorer', '/select,', str(p)])
        elif chosen is act_rename:
            if managed:
                notice(self, '不能重命名',
                       '这个文件受 GitHub 管理，改名会中断仓库中的历史记录。\n'
                       '如果确实要改名，请先在文件上选择「从管理中移除」。',
                       kind='warning')
            else:
                self._rename_file(p)
        elif chosen is act_manage:
            if managed and group is not None:
                self._remove_from_managed(p, group)
            else:
                self.manage_folder_for(p, existing=group)

    def _remove_from_managed(self, path: Path, group: dict) -> None:
        """把一篇笔记移出白名单；下次推送时它会从仓库里消失。"""
        if not ask(self, '从管理中移除',
                   f'「{path.name}」将不再推送到 GitHub。\n\n'
                   f'下次推送时，它会从仓库里移除（本地文件不受影响）。',
                   ok_text='移除', danger=True):
            return
        names = [n for n in core_config.managed_names(group) if n != path.name]
        core_config.set_files(self._cfg, str(group.get('id')), names)
        try:
            core_config.save(self._cfg)
        except OSError as exc:
            notice(self, '没能保存配置', str(exc), kind='error')
            return
        self._refresh_all()

    def _rename_file(self, p: Path) -> None:
        new_name, ok = QInputDialog.getText(self, '重命名', '新的文件名：', text=p.name)
        if not ok or not new_name or new_name == p.name:
            return
        target = p.with_name(new_name)
        if target.exists():
            notice(self, '重命名失败', f'{new_name} 已经存在。', kind='warning')
            return
        try:
            p.rename(target)
        except OSError as exc:
            notice(self, '重命名失败', str(exc), kind='error')
            return
        if self._current == p:
            self._current = target
            self._refresh_title()
        idx = self._recent.index(str(p)) if str(p) in self._recent else -1
        if idx >= 0:
            self._recent[idx] = str(target)
            self._save_recent()
            self.sidebar.set_recent(self._recent)

    # ───────────────────────── 拖放 ─────────────────────────

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and fileio.is_probably_text(p):
                self.load_path(str(p))
                break

    # ───────────────────────── 无边框窗口缩放 ─────────────────────────

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._enable_taskbar_minimize()

    def _enable_taskbar_minimize(self) -> None:
        """Windows：无边框窗口默认缺 ``WS_MINIMIZEBOX``，点任务栏图标不会最小化。

        Windows 判定「这个窗口能不能被任务栏最小化」看的是窗口样式位，
        而 ``Qt.FramelessWindowHint`` 建出来的 WS_POPUP 窗口恰好没有它 ——
        表现就是：标题栏的最小化按钮好使，任务栏图标点了却毫无反应。
        把 ``WS_MINIMIZEBOX``（顺带 ``WS_MAXIMIZEBOX``，Win+Up 同理）补上即可，
        不影响 WM_NCHITTEST 的缩放判定。
        """
        if not _IS_WINDOWS or self._taskbar_fixed:
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            user32.SetWindowLongW(hwnd, GWL_STYLE,
                                  style | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
            self._taskbar_fixed = True
        except Exception:  # noqa: BLE001 - 修不上就维持现状，别让窗口起不来
            pass

    def nativeEvent(self, event_type, message):  # noqa: N802
        """Windows：用 ``WM_NCHITTEST`` 把边缘判定交还给系统。

        一旦返回 ``HTLEFT`` / ``HTTOPRIGHT`` 这类命中代码，Windows 就自己接管光标形状
        与拖拽缩放。这比在 Qt 层算坐标可靠得多，而且**不受子控件遮挡影响** ——
        系统问的是「窗口的哪个部位」，而不是「窗口里哪个控件收到了鼠标」。
        """
        if _IS_WINDOWS and event_type == b'windows_generic_MSG':
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == _WM_NCHITTEST:
                hit = self._hit_test(int(msg.lParam))
                if hit is not None:
                    return True, hit
        return super().nativeEvent(event_type, message)

    def _hit_test(self, lparam: int) -> int | None:
        """把鼠标位置翻译成 Windows 的命中代码；不在边缘时返回 ``None``（交回 Qt）。"""
        if self.isMaximized() or self.isFullScreen():
            return None

        # lParam 的低 16 位是 x、高 16 位是 y，均为**屏幕物理像素**
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value

        # Qt 给的窗口位置 / 尺寸是逻辑像素，乘回设备像素比才能与上面比较
        dpr = self.devicePixelRatioF() or 1.0
        left = round(self.x() * dpr)
        top = round(self.y() * dpr)
        right = left + round(self.width() * dpr)
        bottom = top + round(self.height() * dpr)
        m = round(self.RESIZE_MARGIN * dpr)

        on_left = x < left + m
        on_right = x >= right - m
        on_top = y < top + m
        on_bottom = y >= bottom - m
        if not (on_left or on_right or on_top or on_bottom):
            return None

        if on_top and on_left:
            return _HTTOPLEFT
        if on_top and on_right:
            return _HTTOPRIGHT
        if on_bottom and on_left:
            return _HTBOTTOMLEFT
        if on_bottom and on_right:
            return _HTBOTTOMRIGHT
        if on_left:
            return _HTLEFT
        if on_right:
            return _HTRIGHT
        if on_top:
            return _HTTOP
        return _HTBOTTOM

    def _edge_at(self, pos: QPoint) -> Qt.Edges | None:
        m = self.RESIZE_MARGIN
        rect = self.rect()
        left = pos.x() <= m
        right = pos.x() >= rect.width() - m
        top = pos.y() <= m
        bottom = pos.y() >= rect.height() - m
        if not (left or right or top or bottom):
            return None
        edges = Qt.Edges()
        if left:
            edges |= Qt.LeftEdge
        if right:
            edges |= Qt.RightEdge
        if top:
            edges |= Qt.TopEdge
        if bottom:
            edges |= Qt.BottomEdge
        return edges

    def _update_cursor_shape(self, pos: QPoint) -> None:
        edges = self._edge_at(pos)
        if edges is None:
            self.unsetCursor()
            return
        left = bool(edges & Qt.LeftEdge)
        right = bool(edges & Qt.RightEdge)
        top = bool(edges & Qt.TopEdge)
        bottom = bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            self.setCursor(Qt.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.SizeVerCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self.isMaximized():
            self._update_cursor_shape(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edges = self._edge_at(event.position().toPoint())
            if edges is not None:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)
