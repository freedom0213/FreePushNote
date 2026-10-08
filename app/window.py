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
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from core import config as core_config

from . import fileio, icons, theme
from .widgets.editor import CodeEditor
from .widgets.panel import PanelRail, PushPanel
from .widgets.sidebar import Sidebar, SidebarRail
from .widgets.statusbar import StatusBar
from .widgets.titlebar import TitleBar
from .widgets.toolbar import EditorToolBar

RECENT_PATH = core_config.CONFIG_DIR / 'recent.json'
UI_STATE_PATH = core_config.CONFIG_DIR / 'ui.json'
RECENT_MAX = 12


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
    RESIZE_MARGIN = 6

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('FreePushNote')
        self.setWindowIcon(icons.app_icon())
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(theme.WIN_MIN_W, theme.WIN_MIN_H)
        self.resize(theme.WIN_W + 2 * self.RESIZE_MARGIN,
                    theme.WIN_H + 2 * self.RESIZE_MARGIN)
        self.setAcceptDrops(True)
        # 不开 mouseTracking 的话，鼠标「不按键」掠过边缘时收不到 mouseMoveEvent，
        # 光标就不会变成缩放箭头
        self.setMouseTracking(True)

        # 运行态
        self._current: Path | None = None
        self._encoding = 'utf-8'
        self._eol = 'crlf'
        self._dirty = False
        self._recent: list[str] = self._load_recent()

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
        self._outer.setContentsMargins(*([self.RESIZE_MARGIN] * 4))

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
        center_lay.addWidget(self._editor_stack, 1)

        self.panel = PushPanel()
        self.panel.collapse_requested.connect(lambda: self.toggle_panel(False))
        self.panel.push_requested.connect(self.on_push)
        self.panel.pull_requested.connect(self.on_pull)
        self.panel.diff_requested.connect(self.on_diff)
        self.panel.settings_requested.connect(self.open_settings)
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
            QMessageBox.warning(self, '文件不存在', f'找不到这个文件：\n{p}')
            self._drop_recent(str(p))
            return
        try:
            text, enc, eol = fileio.read_text(p)
        except OSError as exc:
            QMessageBox.warning(self, '打不开这个文件', f'{p}\n\n{exc}')
            return

        self._current = p
        self._encoding = enc
        self._eol = eol
        self.editor.load_text(text)
        self._editor_stack.setCurrentIndex(1)
        self._dirty = False
        self._push_recent(str(p))
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
            QMessageBox.warning(self, '保存失败', f'{self._current}\n\n{exc}')
            return False
        self._dirty = False
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
            self._push_recent(path)
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

    def _push_recent(self, path: str) -> None:
        if path in self._recent:
            self._recent.remove(path)
        self._recent.insert(0, path)
        del self._recent[RECENT_MAX:]
        self._save_recent()
        self.sidebar.set_recent(self._recent)

    def _drop_recent(self, path: str) -> None:
        if path in self._recent:
            self._recent.remove(path)
            self._save_recent()
            self.sidebar.set_recent(self._recent)

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

    def _refresh_sync(self) -> None:
        """阶段 1 只有两种状态；阶段 2 接入绑定后会扩展成完整的四象限。"""
        if self._editor_stack.currentIndex() != 1:
            self.panel.set_sync_state('unmanaged')
            self.panel.set_push_state('disabled')
            self.statusbar.set_sync('unmanaged')
            self.rail.set_sync_state('unmanaged')
            return

        state = 'pending' if self._dirty else 'unmanaged'
        self.panel.set_sync_state(state)
        if self._dirty:
            self.panel.set_push_state('ready')
        else:
            # 已打开、但还没纳入管理：按钮要能点，点了进纳管引导。
            # 灰着不给任何反应是最糟的——用户会以为软件坏了。
            self.panel.set_push_state('ready', text='纳入 GitHub 管理')
        self.statusbar.set_sync(state)
        self.rail.set_sync_state(state)

    def _refresh_all(self) -> None:
        self._refresh_title()
        self._update_cursor()
        self._refresh_encoding()
        self._refresh_sync()
        self.toolbar.set_has_file(self._current is not None
                                  or self._editor_stack.currentIndex() == 1)
        self.statusbar.set_owner(None, None)
        self.panel.set_repo(None, None, None)
        self.sidebar.highlight_recent(str(self._current) if self._current else None)
        self.panel.set_changes([])
        self.panel.set_history([])

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
        """最大化 / 全屏时不留那圈透明边，否则内容会凭空缩进一圈。"""
        m = 0 if (self.isMaximized() or self.isFullScreen()) else self.RESIZE_MARGIN
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
        if self._editor_stack.currentIndex() == 0:
            return
        QMessageBox.information(
            self, '还没有关联仓库',
            '这个文件还没有纳入 GitHub 管理，所以现在还不能推送。\n\n'
            '下一步会做的事：\n'
            '  1. 选择要纳入管理的文件（同一文件夹里可以逐个勾选）\n'
            '  2. 关联一个 GitHub 仓库\n'
            '  3. 之后点 Push 就会自动推送\n\n'
            '这套引导目前还没接入，先把编辑与保存跑通。')

    def on_pull(self) -> None:
        QMessageBox.information(self, '尚未接入', 'Pull 会在绑定仓库后开放。')

    def on_diff(self) -> None:
        QMessageBox.information(self, '尚未接入', '查看差异会在绑定仓库后开放。')

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
        if self._editor_stack.currentIndex() == 0:
            return
        text, ok = QInputDialog.getText(self, '在当前文件中查找', '要查找的内容：')
        if not ok or not text:
            return
        if not self.editor.find(text):
            # 回到开头再找一次，这样可以从中间继续
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            if not self.editor.find(text):
                QMessageBox.information(self, '没有找到', f'没有找到「{text}」。')

    # ───────────────────────── 侧栏右键菜单 ─────────────────────────

    def _show_file_menu(self, path: str, global_pos: QPoint) -> None:
        from PySide6.QtWidgets import QMenu
        p = Path(path)
        managed = False     # 阶段 2 接入绑定表后改为真实判断

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
                QMessageBox.information(
                    self, '不能重命名',
                    '这个文件受 GitHub 管理，改名会中断仓库中的历史记录。\n'
                    '如果确实要改名，请先在文件上选择「从管理中移除」。')
            else:
                self._rename_file(p)
        elif chosen is act_manage:
            QMessageBox.information(self, '尚未接入', '纳管 / 移除会在绑定流程接入后开放。')

    def _rename_file(self, p: Path) -> None:
        new_name, ok = QInputDialog.getText(self, '重命名', '新的文件名：', text=p.name)
        if not ok or not new_name or new_name == p.name:
            return
        target = p.with_name(new_name)
        if target.exists():
            QMessageBox.warning(self, '重命名失败', f'{new_name} 已经存在。')
            return
        try:
            p.rename(target)
        except OSError as exc:
            QMessageBox.warning(self, '重命名失败', str(exc))
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
