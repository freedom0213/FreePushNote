# -*- coding: utf-8 -*-
"""纳管一个文件夹：步骤 1/2 勾选文件 → 步骤 2/2 关联仓库（设计稿 V3-03 / V3-04）。

为什么必须有这一步
------------------
一个笔记文件夹里常常混着不想公开的东西（密码、私人记录、没写完的草稿）。
所以「绑定文件夹」**不能**等于「发布整个文件夹」—— 必须让用户逐个勾选。

而且没勾选的文件不是「被规则挡住」，而是**根本不会被复制进工作区**
（见 :mod:`core.pipeline`）—— 物理上没有机会进入提交。

对话框只负责收集与校验，产出 ``self.group``；落库与后续推送由调用方接手。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from core import config

from .. import icons, theme
from .dialogbase import CheckButton, FramedDialog, label, note_box


def _mono(color: str, size: float, weight: int = 400) -> str:
    return (f'color: {color}; font-size: {size}px; font-weight: {weight};'
            f'font-family: {theme.MONO_STACK};')


def _meta_text(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return ''
    size = st.st_size
    shown = f'{size / 1024:.1f} KB' if size >= 1024 else f'{size} B'
    when = datetime.fromtimestamp(st.st_mtime).strftime('%m-%d %H:%M')
    return f'{shown} · {when}'


def _path_box(path_text: str) -> tuple[QWidget, QHBoxLayout, QLabel]:
    """文件夹路径条：图标 + 等宽路径 + 右侧说明。返回 ``(容器, 布局, 右侧标签)``。"""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(11, 0, 11, 0)
    lay.setSpacing(8)

    icon = QLabel()
    icon.setPixmap(icons.icon('folder', theme.TEXT_SECOND, 13).pixmap(13, 13))
    icon.setFixedSize(13, 13)
    lay.addWidget(icon)

    path = label(path_text, theme.TEXT_PRIMARY, theme.FS_TINY, mono=True)
    path.setToolTip(path_text)
    lay.addWidget(path, 1)

    right = label('', theme.TEXT_MUTED, theme.FS_LABEL, mono=True)
    lay.addWidget(right)

    box.setFixedHeight(34)
    box.setStyleSheet(f'background: {theme.BG_INPUT};'
                      f'border: 1px solid {theme.BORDER}; border-radius: 4px;')
    return box, lay, right


class _FileRow(QWidget):
    """一行文件：复选框 + 文件名 + 大小与时间。整行可点。"""

    def __init__(self, name: str, meta: str, checked: bool, on_toggle) -> None:
        super().__init__()
        self.name = name
        self._on_toggle = on_toggle

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 8, 0)
        lay.setSpacing(9)

        self.check = CheckButton(checked)
        lay.addWidget(self.check)

        self._title = label(name, theme.TEXT_BODY, theme.FS_UI, mono=True)
        lay.addWidget(self._title, 1)

        self._meta = label(meta, theme.TEXT_FAINT, theme.FS_LABEL, mono=True)
        lay.addWidget(self._meta)

        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.check.clicked.connect(self._notify)
        self._sync_look()

    def _notify(self) -> None:
        self._sync_look()
        self._on_toggle(self.name, self.check.isChecked())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.check.setChecked(not self.check.isChecked())
            self._notify()
        super().mousePressEvent(event)

    def _sync_look(self) -> None:
        on = self.check.isChecked()
        self._title.setStyleSheet(_mono(theme.TEXT_BODY if on else theme.TEXT_GHOST,
                                        theme.FS_UI))
        self._meta.setStyleSheet(_mono(theme.TEXT_FAINT if on else theme.TEXT_GHOST,
                                       theme.FS_LABEL))

    def set_checked(self, value: bool) -> None:
        self.check.setChecked(value)
        self._sync_look()


class ManageFolderDialog(FramedDialog):
    """``exec()`` 返回 Accepted 时，``self.group`` 是一个校验通过的分组字典。"""

    def __init__(self, folder: str | Path, *, preselect: list[str] | None = None,
                 existing: dict | None = None, parent=None) -> None:
        super().__init__('纳入 GitHub 管理', parent, icon_name='folder', width=500)

        self._folder = Path(folder)
        self._existing = dict(existing) if existing else None
        self.group: dict | None = None

        self._files = config.scan_notes(self._folder)
        wanted = preselect if preselect is not None else (
            (existing or {}).get('files') or [])
        self._checked = {n for n in self._files if n in set(wanted)}
        self._rows: dict[str, _FileRow] = {}

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_files_page())
        self._stack.addWidget(self._build_repo_page())
        self.body.addWidget(self._stack)

        self._btn_cancel = self.add_ghost('取消')
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_back = self.add_ghost('上一步')
        self._btn_back.clicked.connect(lambda: self._go(0))
        self._btn_next = self.add_primary('下一步')
        self._btn_next.clicked.connect(self._next)

        self._go(0)
        self._sync_counts()
        self.finish()

    # ───────────────────────── 步骤 1：选文件 ─────────────────────────

    def _build_files_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        lay.addWidget(label(
            '勾选要推到 GitHub 的文件。没勾选的文件不会离开这台电脑 ——'
            '它们不会被复制到推送工作区，物理上没机会上传。',
            theme.TEXT_SECOND, theme.FS_TINY, wrap=True))

        box, _lay, self._files_hint = _path_box(str(self._folder))
        self._files_hint.setText(f'共 {len(self._files)} 个')
        lay.addWidget(box)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        self._cb_all = CheckButton(True)
        self._cb_all.clicked.connect(self._toggle_all)
        sel_row.addWidget(self._cb_all)
        self._all_hint = label('全选', theme.TEXT_BODY, theme.FS_UI)
        sel_row.addWidget(self._all_hint)
        sel_row.addStretch(1)
        self._sel_count = label('', theme.TEXT_MUTED, theme.FS_LABEL, mono=True)
        sel_row.addWidget(self._sel_count)
        lay.addLayout(sel_row)

        if self._files:
            scroll = QScrollArea()
            scroll.setObjectName('ScrollHost')
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFixedHeight(230)
            host = QWidget()
            inner = QVBoxLayout(host)
            inner.setContentsMargins(4, 5, 4, 5)
            inner.setSpacing(1)
            for name in self._files:
                row = _FileRow(name, _meta_text(self._folder / name),
                               name in self._checked, self._on_row_toggle)
                self._rows[name] = row
                inner.addWidget(row)
            inner.addStretch(1)
            scroll.setWidget(host)
            lay.addWidget(scroll)
        else:
            lay.addWidget(note_box(
                '这个文件夹里没有 .txt 或 .md 文件。换一个文件夹，'
                '或者先往里面放一篇笔记。', 'warn'))
            lay.addStretch(1)
        return page

    def _build_repo_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        lay.addWidget(label('把这个文件夹关联到一个 GitHub 仓库，之后点 Push 就会自动推送。',
                            theme.TEXT_SECOND, theme.FS_TINY, wrap=True))

        box, _lay, self._picked_hint = _path_box(str(self._folder))
        lay.addWidget(box)

        lay.addWidget(note_box(
            '仓库里只会出现你勾选的笔记，以及为它们自动生成的文档站。', 'warn'))

        field = QVBoxLayout()
        field.setSpacing(7)
        field.addWidget(label('仓库地址', theme.TEXT_BODY, theme.FS_UI, 600))
        self._repo = QLineEdit()
        self._repo.setObjectName('Input')
        self._repo.setFixedHeight(38)
        self._repo.setPlaceholderText('owner/name，或直接粘贴 GitHub 上的仓库链接')
        if self._existing:
            self._repo.setText(str(self._existing.get('repo') or ''))
        field.addWidget(self._repo)
        field.addWidget(label('支持 owner/name、https 链接、git@ 链接三种写法',
                              theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))
        lay.addLayout(field)

        site_row = QHBoxLayout()
        site_row.setSpacing(8)
        self._cb_site = CheckButton(bool((self._existing or {}).get('site', True)))
        site_row.addWidget(self._cb_site)
        site_row.addWidget(label('同时生成在线文档站（推荐）', theme.TEXT_BODY,
                                 theme.FS_UI))
        site_row.addStretch(1)
        lay.addLayout(site_row)
        lay.addWidget(label(
            '会生成一个 docsify 站点放进仓库，手机浏览器就能阅读。需要在仓库的 '
            'Settings → Pages 里把来源设为 main 分支根目录（一次性设置）。',
            theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))

        self._err = label('', theme.ERROR, theme.FS_TINY, wrap=True)
        self._err.setVisible(False)
        lay.addWidget(self._err)
        lay.addStretch(1)
        return page

    # ───────────────────────── 交互 ─────────────────────────

    def _on_row_toggle(self, name: str, checked: bool) -> None:
        (self._checked.add if checked else self._checked.discard)(name)
        self._sync_counts()

    def _toggle_all(self) -> None:
        on = self._cb_all.isChecked()
        for name, row in self._rows.items():
            row.set_checked(on)
            (self._checked.add if on else self._checked.discard)(name)
        self._sync_counts()

    def _sync_counts(self) -> None:
        total = len(self._files)
        picked = len(self._checked)
        self._sel_count.setText(f'已选 {picked} / 共 {total}')
        self._sel_count.setStyleSheet(
            _mono(theme.TEXT_MUTED if picked else theme.WARNING, theme.FS_LABEL))
        self._all_hint.setText('全选' if picked < total else '已全选')
        self._cb_all.setChecked(picked == total and total > 0)
        self._picked_hint.setText(f'已选 {picked} 个')
        self._btn_next.setEnabled(picked > 0)

    def _go(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        first = index == 0
        self.set_subtitle('步骤 1 / 2 · 选择要管理的文件' if first
                          else '步骤 2 / 2 · 关联仓库')
        self._btn_back.setVisible(not first)
        if first:
            self._btn_next.setText('  下一步')
            self._btn_next.setIcon(icons.icon('chevron-right', '#FFFFFF', 13))
        else:
            self._btn_next.setText('  绑定并推送')
            self._btn_next.setIcon(icons.icon('push', '#FFFFFF', 13))
            self._repo.setFocus()
        self._err.setVisible(False)
        self.finish()

    def _next(self) -> None:
        if self._stack.currentIndex() == 0:
            if self._checked:
                self._go(1)
            return
        if self._build_group() is not None:
            self.accept()

    # ───────────────────────── 产出 ─────────────────────────

    def _build_group(self) -> dict | None:
        try:
            cfg = config.load()
        except config.ConfigError as exc:
            self._show_error([str(exc)])
            return None

        group = (dict(self._existing) if self._existing
                 else config.new_group(self._folder))
        group['folder'] = str(self._folder)
        group.setdefault('name', self._folder.name)
        group['site'] = self._cb_site.isChecked()
        if not group.get('id'):
            group['id'] = config.make_group_id(cfg, self._folder.name)
        group['files'] = [n for n in self._files if n in self._checked]
        group['repo'] = config.parse_repo_spec(self._repo.text()) or ''

        errs = config.validate_group(group, cfg)
        if not group['repo']:
            errs.append('仓库地址看不懂。可以填 owner/name，'
                        '或直接粘贴 https://github.com/owner/name')
        if errs:
            self._show_error(errs)
            return None

        self.group = group
        return group

    def _show_error(self, messages: list[str]) -> None:
        self._err.setText('· ' + '\n· '.join(messages))
        self._err.setStyleSheet(
            f'color: {theme.ERROR}; font-size: {theme.FS_TINY}px;'
            f'font-family: {theme.UI_STACK};')
        self._err.setVisible(True)
        self.finish()
