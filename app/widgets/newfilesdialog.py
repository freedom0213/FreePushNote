# -*- coding: utf-8 -*-
"""推送前发现「未纳入管理的新文件」时的提示面板（设计稿 S-02）。

它解决的是一个很具体的困惑：**我明明新建了个 txt，怎么没同步？**

用户不会记得自己当初勾了哪些文件，而软件又刻意「不勾选就不上传」——
两个都对，合起来就产生了一个沉默的缺口。所以在点推送时主动扫一遍，
把没纳管的文件摆出来问一次。

两条刻意的规则：

1. **取消勾选 = 以后不再提示**（稿子原文：「取消勾选的文件保持不管控，
   下次不再提示」）。否则每次推送都要被同一批文件烦一遍。
   文件没有丢，仍然可以在左栏右键「纳入 GitHub 管理」加回来。
2. **直接关掉面板 = 取消这次推送**，什么清单都不改。
   关闭一个对话框不应该悄悄把东西推上去。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from .. import theme
from .dialogbase import FileRow, FramedDialog, label

#: 列表最多占多高 —— 文件夹里可能有几十篇，不能把面板撑破屏幕
LIST_MAX_H = 198


def _when(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).strftime('%m-%d %H:%M')


class NewFilesDialog(FramedDialog):
    """``exec()`` 返回 Accepted 后，读 ``mode`` / ``picked`` / ``skipped``。

    - ``mode == 'include'``：用户点了「纳入并推送」→ 勾选的该进白名单
    - ``mode == 'managed_only'``：用户点了「只推已管理的」→ 白名单不动
    - ``picked`` 勾选的、``skipped`` 未勾选的（未勾选的一律记入不再提示）
    """

    def __init__(self, files: list[dict], group: dict, parent=None) -> None:
        count = len(files)
        super().__init__(f'发现 {count} 个未纳入管理的文件', parent,
                         icon_name='file', width=460)

        self.mode = 'include'
        self.picked: list[str] = []
        self.skipped: list[str] = []
        self._files = list(files)
        self._rows: dict[str, FileRow] = {}

        folder = str(group.get('folder') or '')
        if folder:
            # 稿子没画这一行，但多分组时「这个文件夹」是指哪一个并不显然
            self.set_subtitle(folder)

        self.body.addWidget(label(
            '它们在这个文件夹里，但还没有纳入 GitHub 管理。要一起推送吗？',
            theme.TEXT_SECOND, theme.FS_SMALL, wrap=True))
        self.body.addWidget(self._build_list())
        self.body.addWidget(label(
            '取消勾选的文件保持不管控，下次不再提示。',
            theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))

        self._btn_managed = self.add_ghost('只推已管理的')
        self._btn_managed.clicked.connect(lambda: self._done('managed_only'))
        self._btn_include = self.add_primary('纳入并推送', 'push')
        self._btn_include.clicked.connect(lambda: self._done('include'))

        self.finish()

    # ───────────────────────── 列表 ─────────────────────────

    def _build_list(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName('ScrollHost')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        host = QWidget()
        inner = QVBoxLayout(host)
        inner.setContentsMargins(4, 5, 4, 5)
        inner.setSpacing(1)

        for f in self._files:
            name = str(f.get('name') or '')
            row = FileRow(name, _when(float(f.get('mtime') or 0)), True)
            self._rows[name] = row
            inner.addWidget(row)
        inner.addStretch(1)
        scroll.setWidget(host)

        # 行数少时不要把面板撑出一块空白
        scroll.setFixedHeight(min(LIST_MAX_H, 10 + 30 * len(self._files)))
        return scroll

    # ───────────────────────── 产出 ─────────────────────────

    def _done(self, mode: str) -> None:
        self.mode = mode
        self.picked = [n for n, r in self._rows.items() if r.check.isChecked()]
        self.skipped = [n for n, r in self._rows.items() if not r.check.isChecked()]
        self.accept()


def summarize(files: list[dict]) -> str:
    """给日志/提示用的一句话（不含 UI 细节）。"""
    names = '、'.join(str(f.get('name') or '') for f in files[:4])
    more = f' 等 {len(files)} 篇' if len(files) > 4 else ''
    return f'{names}{more}'


__all__ = ['NewFilesDialog', 'summarize']
