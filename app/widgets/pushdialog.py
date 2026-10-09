# -*- coding: utf-8 -*-
"""推送前的确认（设计稿 S-01）。

界面上只有三件事，顺序就是用户的心智顺序：

    ① 这次要推什么     —— 逐篇笔记的增删行数，可取消勾选
    ② 提交信息         —— 默认已生成，可以直接改成「补充 Redis 八股的一节」
    ③ 确认             —— 按下去才真的提交并推送

为什么是**两阶段**而不是一次推完：用户在按下去之前应该能看清这次会改什么。
所以进这个对话框之前，内容已经同步进工作区并暂存好了（全是本地操作、不联网），
这里的数字是 ``git diff --cached --numstat`` 读出来的**真实值**，不是估算。

取消勾选某篇笔记 = 这次不提交它的改动，**改动仍然留在本地**，下次推送再带上
（见 :func:`core.pipeline.finalize_push` 的 ``keep`` 参数）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from core import config

from .. import theme
from .dialogbase import CheckButton, FramedDialog, label, note_box


def _mono(color: str, size: float, weight: int = 400) -> str:
    return (f'color: {color}; font-size: {size}px; font-weight: {weight};'
            f'font-family: {theme.MONO_STACK};')


class _ChangeRow(QWidget):
    """一行改动：复选框 + 笔记名 + ``+N −M``。"""

    def __init__(self, name: str, added: int, removed: int, checked: bool,
                 on_toggle) -> None:
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

        plus = label(f'+{added}', theme.SUCCESS, theme.FS_LABEL, 500, mono=True)
        minus = label(f'−{removed}', theme.ERROR, theme.FS_LABEL, 500, mono=True)
        lay.addWidget(plus)
        lay.addWidget(minus)
        self._plus, self._minus = plus, minus

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
        for lab, base in ((self._plus, theme.SUCCESS), (self._minus, theme.ERROR)):
            lab.setStyleSheet(_mono(base if on else theme.TEXT_GHOST,
                                    theme.FS_LABEL, 500))

    def set_checked(self, value: bool) -> None:
        self.check.setChecked(value)
        self._sync_look()


class PushDialog(FramedDialog):
    """``exec()`` 返回 Accepted 后读 ``self.message`` 与 ``self.keep``。"""

    def __init__(self, group: dict, staged, parent=None) -> None:
        repo = group.get('repo') or '（未关联仓库）'
        super().__init__('推送到 GitHub', parent, icon_name='push', width=520,
                         icon_color=theme.PRIMARY)

        self.message = ''
        self.keep: list[str] | None = None

        self._group = group
        self._staged = staged
        self._checked: set[str] = set()

        # 逐篇笔记的增删行数（把笔记自己和它的页面合在一起算）
        by_path = {c['path']: c for c in staged.changes}
        self._notes: dict[str, tuple[int, int]] = {}
        for name, paths in staged.note_paths.items():
            added = sum(int(by_path.get(p, {}).get('added', 0)) for p in paths)
            removed = sum(int(by_path.get(p, {}).get('removed', 0)) for p in paths)
            self._notes[name] = (added, removed)

        self._checked = set(self._notes)

        self._build(repo, len(staged.changes))
        self._sync_total()
        self.finish()

    # ───────────────────────── 构建 ─────────────────────────

    def _build(self, repo: str, total_files: int) -> None:
        self.body.addWidget(label(f'这些改动会被推送到 {repo}。',
                                  theme.TEXT_SECOND, theme.FS_TINY, wrap=True))

        field = QVBoxLayout()
        field.setSpacing(7)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label('本次提交信息', theme.TEXT_BODY, theme.FS_UI, 600))
        head.addStretch(1)
        head.addWidget(label('自动生成，可以改', theme.TEXT_FAINT, theme.FS_LABEL))
        field.addLayout(head)

        self._msg = QLineEdit()
        self._msg.setObjectName('Input')
        self._msg.setFixedHeight(38)
        self._msg.setText(config.default_commit_message(
            self._group, list(self._notes) or None))
        field.addWidget(self._msg)
        field.addWidget(label('这句话会出现在 GitHub 的提交记录里，方便以后回看。',
                              theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))
        self.body.addLayout(field)

        head2 = QHBoxLayout()
        head2.setSpacing(8)
        head2.addWidget(label('本次推送的改动', theme.TEXT_BODY, theme.FS_UI, 600))
        head2.addStretch(1)
        self._total = label('', theme.WARNING, theme.FS_LABEL, mono=True)
        head2.addWidget(self._total)
        self.body.addLayout(head2)

        scroll = QScrollArea()
        scroll.setObjectName('ScrollHost')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._rows: dict[str, _ChangeRow] = {}
        host = QWidget()
        inner = QVBoxLayout(host)
        inner.setContentsMargins(4, 5, 4, 5)
        inner.setSpacing(1)

        for name, (added, removed) in self._notes.items():
            row = _ChangeRow(name, added, removed, True, self._on_toggle)
            self._rows[name] = row
            inner.addWidget(row)

        artifact_rows = 0
        if self._staged.artifact_paths:
            artifact_rows = 1
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 0, 8, 0)
            rl.setSpacing(9)
            spacer = QWidget()
            spacer.setFixedWidth(20)          # 与上面复选框对齐
            rl.addWidget(spacer)
            rl.addWidget(label('自动生成的文档站', theme.TEXT_MUTED, theme.FS_UI), 1)
            # 刻意**不显示行数**：index.html 动辄几十行，把 +95 摆在用户面前
            # 只会让人以为「我改了这么多？」—— 它跟着笔记走，不是用户的改动
            rl.addWidget(label(f"{len(self._staged.artifact_paths)} 个文件",
                               theme.TEXT_FAINT, theme.FS_LABEL, mono=True))
            row.setFixedHeight(30)
            row.setToolTip('随笔记一起生成，不需要单独开关')
            inner.addWidget(row)

        inner.addStretch(1)
        scroll.setWidget(host)
        # 行高 ≈ 31px；不留够高会把最后一行切掉一半
        rows = max(1, len(self._notes) + artifact_rows)
        scroll.setFixedHeight(min(232, 31 * rows + 14))
        self.body.addWidget(scroll)

        self.body.addWidget(note_box(
            '取消勾选的笔记这次不会推送，改动仍然保留在本地，下次推送再带上。',
            'info', icon_name='alert-circle'))

        self._btn_cancel = self.add_ghost('取消')
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_push = self.add_primary('Push', 'push')
        self._btn_push.clicked.connect(self._accept)

    # ───────────────────────── 交互 ─────────────────────────

    def _on_toggle(self, name: str, checked: bool) -> None:
        (self._checked.add if checked else self._checked.discard)(name)
        self._sync_total()

    def _sync_total(self) -> None:
        """汇总只统计**笔记**的增删行数。

        站点产物的行数（index.html 之类）不计入 —— 那不是用户改的内容，
        混进来会让「这次改了多少」这件事变得不可读。
        """
        added = sum(self._notes[n][0] for n in self._checked)
        removed = sum(self._notes[n][1] for n in self._checked)
        self._total.setText(f'{len(self._checked)} 篇 · +{added} −{removed}')
        self._btn_push.setEnabled(bool(self._checked))
        self._total.setStyleSheet(_mono(
            theme.WARNING if self._checked else theme.ERROR, theme.FS_LABEL))

    def _accept(self) -> None:
        self.message = self._msg.text().strip()
        keep: list[str] = list(self._staged.artifact_paths)
        for name in self._checked:
            keep.extend(self._staged.note_paths.get(name, []))
        self.keep = keep
        self.accept()
