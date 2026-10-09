# -*- coding: utf-8 -*-
"""左侧栏（200px 可收起）。

分上下两层，这是用户对着 WorkBuddy 的侧栏结构指定的：

1. **最近打开** —— 不受 GitHub 管理的 txt。关掉软件后这个列表仍然保留
   （持久化在 ``~/.pushnote/recent.json``），下次打开还在。
   排序规则是用户定的：**点开看看不会改变顺序，只有保存过才提到第一位** ——
   否则「随手翻了几篇」就把顺序搅乱了。每行右侧悬停会露出一个 ×，可把该条移除。
2. **受管理的文件夹** —— 已纳入 GitHub 管理的分组，每组 = 一个仓库；
   组内的文件就是当初勾选要纳管的那些。

两层可以分别折叠，整栏也能收起（收起后编辑区变宽）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import icons, theme

_ROLE_PATH = Qt.UserRole + 1

#: 行尾为删除按钮预留的宽度 / 按钮本身的大小
_CLOSE_ZONE = 30
_CLOSE_SIZE = 20


def _close_rect(item_rect: QRect) -> QRect:
    """某一行里删除按钮的位置。

    绘制和点击判定**必须用同一个函数**算 —— 分成两处写，迟早会错开几个像素，
    表现成「看着点到了却没反应」，那种 bug 很难查。
    """
    left = item_rect.right() - _CLOSE_ZONE + (_CLOSE_ZONE - _CLOSE_SIZE) // 2
    top = item_rect.top() + (item_rect.height() - _CLOSE_SIZE) // 2
    return QRect(left, top, _CLOSE_SIZE, _CLOSE_SIZE)


class _RecentDelegate(QStyledItemDelegate):
    """给「最近打开」的每一行右侧画一个删除按钮（×）。

    为什么用 delegate 画、而不是每行塞一个 QToolButton 子控件：
    子控件要自己跟着滚动条、窗口缩放手搬位置，漏一处就会错位；
    delegate 是在视口坐标里画的，这些都由列表框架处理掉了。
    """

    def __init__(self, view: 'QListWidget') -> None:
        super().__init__(view)
        self._view = view

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index) -> None:  # noqa: D102
        super().paint(painter, option, index)

        path = index.data(_ROLE_PATH)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = getattr(self._view, 'hover_path', None) == path
        if not (hovered or selected):
            return

        rect = _close_rect(option.rect)
        on_button = hovered and getattr(self._view, 'hover_close', False)

        painter.save()
        if on_button:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.BG_ACTIVE))
            painter.drawRoundedRect(rect, theme.RADIUS_BTN, theme.RADIUS_BTN)
        else:
            # 用行背景盖掉这块，免得长文件名被压在 × 底下
            painter.fillRect(
                rect,
                QColor(theme.BG_SELECTED if selected else
                       theme.BG_HOVER if hovered else theme.BG_PANEL))

        pen = QPen(QColor(theme.TEXT_STRONG if on_button else theme.TEXT_SECOND))
        pen.setWidthF(1.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        c = rect.center()
        d = 3.4
        painter.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        painter.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
        painter.restore()


class _RecentList(QListWidget):
    """「最近打开」列表。

    比普通 QListWidget 多三件事：

    1. 鼠标划过某一行时，行尾显示删除按钮（×）；
    2. 点那个 × 是**从列表移除**，点别处才是**打开文件** ——
       所以在 ``mousePressEvent`` 里就要判断并吃掉这一次点击，
       否则列表还会再发一次 ``itemClicked``，变成「既删掉又打开」；
    3. 悬停状态自己维护（``hover_path`` / ``hover_close``），供 delegate 读取。
    """

    open_requested = Signal(str)      # 留作显式入口；当前由 itemClicked 触发
    remove_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hover_path: str | None = None
        self.hover_close = False
        self.setItemDelegate(_RecentDelegate(self))
        # 不按下也要收到 mouseMove，否则「划过就出现 ×」不会发生
        self.viewport().setMouseTracking(True)

    # ── 悬停追踪 ──

    def _item_at(self, pos) -> QListWidgetItem | None:
        item = self.itemAt(pos)
        return item if (item is not None and item.data(_ROLE_PATH)) else None

    def _set_hover(self, path: str | None, on_button: bool = False) -> None:
        if path == self.hover_path and on_button == self.hover_close:
            return
        self.hover_path, self.hover_close = path, on_button
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        item = self._item_at(pos)
        self._set_hover(item.data(_ROLE_PATH) if item else None,
                        bool(item) and _close_rect(self.visualItemRect(item)).contains(pos))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(None)
        super().leaveEvent(event)

    # ── 点击 ──

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if event.button() == Qt.LeftButton:
            item = self._item_at(pos)
            if item is not None and _close_rect(self.visualItemRect(item)).contains(pos):
                self.remove_requested.emit(item.data(_ROLE_PATH))
                event.accept()
                return                 # 吃掉这一下，别再触发 itemClicked
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # 点 × 的那一下不该把这一行顺手切成「当前文件」
        if event.button() == Qt.LeftButton and self.hover_close:
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _GroupHeader(QFrame):
    """分组标题行：标题文字 + 可选的右侧按钮。"""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(6)

        self._label = QLabel(title)
        self._label.setObjectName('GroupHeader')
        lay.addWidget(self._label)
        lay.addStretch(1)
        self._row = lay

    def add_button(self, icon_name: str, tip: str, color: str = theme.TEXT_WEAK,
                   size: int = 14) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName('WinBtn')
        btn.setIcon(icons.icon(icon_name, color, size))
        btn.setIconSize(QSize(size, size))
        btn.setFixedSize(24, 24)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setAutoRaise(True)
        self._row.addWidget(btn)
        return btn

    def set_title(self, text: str) -> None:
        self._label.setText(text)


class Sidebar(QFrame):
    """左侧栏。只负责「显示 + 抛信号」，不做任何文件操作。"""

    file_activated = Signal(str)            # 最近打开列表里的某个 txt
    managed_file_activated = Signal(str)    # 受管理文件夹里的某个 txt
    recent_removed = Signal(str)            # 把某条从「最近打开」里移除
    new_note_requested = Signal()
    collapse_requested = Signal()
    context_requested = Signal(str, object)  # (路径, 全局坐标 QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('Sidebar')
        self.setFixedWidth(theme.SIDEBAR_W)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 第一组：最近打开 ──
        self._recent_header = _GroupHeader('最近打开')
        self._recent_header.add_button('panel-left-hide', '收起侧栏').clicked.connect(
            self.collapse_requested)
        root.addWidget(self._recent_header)

        self.recent_list = _RecentList()
        self.recent_list.setObjectName('NoteTree')
        self.recent_list.setFrameShape(QFrame.NoFrame)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.setTextElideMode(Qt.ElideMiddle)
        self.recent_list.setContentsMargins(8, 0, 8, 0)
        self.recent_list.itemActivated.connect(self._on_recent_activated)
        self.recent_list.itemClicked.connect(self._on_recent_activated)
        self.recent_list.remove_requested.connect(self.recent_removed)
        self.recent_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(self._on_recent_context)
        root.addWidget(self.recent_list)

        empty = QLabel('还没有打开过文件。\n打开一个 txt 后，\n它会出现在这里。')
        empty.setWordWrap(True)
        empty.setStyleSheet(f'color: {theme.TEXT_FAINT}; font-size: {theme.FS_TINY}px;')
        empty.setContentsMargins(16, 8, 12, 8)
        self._recent_empty = empty
        root.addWidget(empty)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f'background: {theme.BORDER};')
        root.addWidget(divider)

        # ── 第二组：受管理的文件夹 ──
        self._managed_header = _GroupHeader('受管理的文件夹')
        root.addWidget(self._managed_header)

        self.managed_tree = QTreeWidget()
        self.managed_tree.setObjectName('NoteTree')
        self.managed_tree.setFrameShape(QFrame.NoFrame)
        self.managed_tree.setHeaderHidden(True)
        self.managed_tree.setIndentation(20)
        self.managed_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.managed_tree.setTextElideMode(Qt.ElideMiddle)
        self.managed_tree.setContentsMargins(8, 0, 8, 0)
        self.managed_tree.itemClicked.connect(self._on_managed_activated)
        self.managed_tree.itemActivated.connect(self._on_managed_activated)
        self.managed_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.managed_tree.customContextMenuRequested.connect(self._on_managed_context)
        root.addWidget(self.managed_tree, 1)

        self._managed_empty = QLabel('还没有纳入 GitHub\n管理的文件夹。')
        self._managed_empty.setWordWrap(True)
        self._managed_empty.setStyleSheet(
            f'color: {theme.TEXT_FAINT}; font-size: {theme.FS_TINY}px;')
        self._managed_empty.setContentsMargins(16, 8, 12, 8)
        root.addWidget(self._managed_empty)

        # ── 底部：新建笔记 ──
        footer = QFrame()
        footer.setFixedHeight(36)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(16, 0, 12, 0)
        f_lay.setSpacing(7)
        plus = QLabel()
        plus.setPixmap(icons.icon('plus', theme.TEXT_MUTED, 13).pixmap(13, 13))
        f_lay.addWidget(plus)
        new_label = QLabel('新建笔记')
        new_label.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: {theme.FS_UI}px;')
        f_lay.addWidget(new_label)
        f_lay.addStretch(1)
        footer.setCursor(Qt.PointingHandCursor)
        footer.setToolTip('新建一个 txt 并保存到磁盘')
        root.addWidget(footer)
        footer.mousePressEvent = lambda _e: self.new_note_requested.emit()  # type: ignore[method-assign]

        self._refresh_empty()

    # ───────────────────────── 数据填充 ─────────────────────────

    def set_recent(self, paths: list[str]) -> None:
        self.recent_list.clear()
        self.recent_list._set_hover(None)      # 行都被重建了，悬停状态一并复位
        for p in paths:
            item = QListWidgetItem(icons.icon('file', theme.TEXT_MUTED, 13),
                                   Path(p).name)
            item.setData(_ROLE_PATH, p)
            item.setToolTip(f'{p}\n\n右侧的 × 可以把这一条从列表里移除')
            item.setSizeHint(QSize(0, 28))
            self.recent_list.addItem(item)
        self._refresh_empty()

    def set_managed(self, groups: list[dict]) -> None:
        """``groups`` = [{name, repo, folder, files: [路径, ...]}, ...]"""
        self.managed_tree.clear()
        for g in groups:
            top = QTreeWidgetItem([g.get('name') or Path(g.get('folder', '')).name])
            top.setIcon(0, icons.icon('chevron-down', theme.TEXT_SECOND, 12))
            top.setData(0, _ROLE_PATH, None)
            top.setToolTip(0, f"{g.get('folder', '')}  →  {g.get('repo', '')}")
            top.setSizeHint(0, QSize(0, 28))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for f in g.get('files') or []:
                child = QTreeWidgetItem([Path(f).name])
                child.setData(0, _ROLE_PATH, f)
                child.setToolTip(0, f)
                child.setSizeHint(0, QSize(0, 28))
                top.addChild(child)
            self.managed_tree.addTopLevelItem(top)
            top.setExpanded(True)
        self._refresh_empty()

    def highlight_recent(self, path: str | None) -> None:
        """让当前正在编辑的文件在「最近打开」里高亮。"""
        for i in range(self.recent_list.count()):
            item = self.recent_list.item(i)
            item.setSelected(bool(path) and item.data(_ROLE_PATH) == path)

    def _refresh_empty(self) -> None:
        self._recent_empty.setVisible(self.recent_list.count() == 0)
        self._managed_empty.setVisible(self.managed_tree.topLevelItemCount() == 0)

    # ───────────────────────── 交互 ─────────────────────────

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        path = item.data(_ROLE_PATH)
        if path:
            self.file_activated.emit(path)

    def _on_managed_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, _ROLE_PATH)
        if path:
            self.managed_file_activated.emit(path)

    def _on_recent_context(self, pos) -> None:
        item = self.recent_list.itemAt(pos)
        if item is not None and item.data(_ROLE_PATH):
            self.context_requested.emit(item.data(_ROLE_PATH),
                                        self.recent_list.viewport().mapToGlobal(pos))

    def _on_managed_context(self, pos) -> None:
        item = self.managed_tree.itemAt(pos)
        if item is not None and item.data(0, _ROLE_PATH):
            self.context_requested.emit(item.data(0, _ROLE_PATH),
                                        self.managed_tree.viewport().mapToGlobal(pos))


class SidebarRail(QFrame):
    """左侧栏收起后的窄条。

    只做一件事：让用户能把它展开回去。

    收起之后如果没有入口，那就不叫「收起」，叫「关掉」—— 上一版就是犯了这个错，
    只能跑到工具栏左上角点「显示侧栏」，用户当场就发现了。现在跟右侧栏对齐：
    **一个按钮，原地切换。**
    """

    expand_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('Sidebar')
        self.setFixedWidth(theme.SIDEBAR_RAIL_W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        btn = QToolButton(self)
        btn.setObjectName('WinBtn')
        btn.setIcon(icons.icon('panel-left-show', theme.TEXT_SECOND, 16))
        btn.setIconSize(QSize(16, 16))
        btn.setFixedSize(theme.SIDEBAR_RAIL_W, theme.TITLEBAR_H)
        btn.setToolTip('展开侧栏（Ctrl+B）')
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.clicked.connect(self.expand_requested)
        lay.addWidget(btn)

        lay.addStretch(1)
