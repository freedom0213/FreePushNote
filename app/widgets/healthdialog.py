# -*- coding: utf-8 -*-
"""「编码与换行符提醒」卡（设计稿 S-03）。

**为什么要这张卡**：记事本「另存为 ANSI」写出的是 GBK，用户不会知道这意味着
"推到 GitHub 上可能是一堆乱码"。状态栏里孤零零一个词太轻了 —— 所以那一项在异常时
变成琥珀胶囊（见 ``statusbar._CodeItem``），点开就是这里：一句话说清后果，再给一个出口。

交互是**用户主动点开**的，不是自动弹窗（设计稿图注：打开非 UTF-8 或 CRLF 的 txt 时，
状态栏对应项变橙色；点它弹出这张卡）。正在写东西的人不该被一次体检打断。

两个出口：

* **保持原样** —— 什么都不改，关掉。用户的文件永远优先。
* **转换后推送** —— 把这篇转成 UTF-8 存盘，然后走一次正常的推送流程。
  只在**编码真的需要转**时才出现。

🔴 换行符那条刻意**不提供"转换"**：把用户的本地文件从 CRLF 改成 LF，会让它在记事本
之外的编辑器里显得不习惯，而这件事对推送结果毫无影响（仓库侧本来就统一 LF）。
设计稿原话也是「本地文件不受影响」。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from .. import icons, theme
from .dialogbase import FramedDialog, label


#: 正文的编码 → 状态栏 / 卡片里显示的名字
def reminder_lines(encoding_key: str, encoding_name: str,
                   eol_key: str) -> list[str]:
    """该提示哪几条（纯函数，便于自测直接断言文案）。

    两条都不是"错误"，只是**用户需要知道的事实**：
    编码那条是后果（GitHub 上可能乱码），换行那条是安抚（我们会替你转，本地不动）。
    """
    lines: list[str] = []
    if encoding_key != 'utf-8':
        lines.append(f'该文件是 {encoding_name} 编码，推送后 GitHub 上可能显示乱码。')
    if eol_key == 'crlf':
        lines.append('本地是 CRLF 换行，推送时会自动转成 LF 存储，本地文件不受影响。')
    return lines


def needs_conversion(encoding_key: str) -> bool:
    """这篇的编码值不值得"转换后推送"。

    只有非 UTF-8 需要转。换行符不转 —— 见模块文档里那条说明。
    """
    return encoding_key != 'utf-8'


def _dot(color: str) -> QFrame:
    """提醒项前面那个 6×6 的小圆点（设计稿里的「点-编码」/「点-换行」）。"""
    d = QFrame()
    d.setFixedSize(6, 6)
    d.setStyleSheet(f'background: {color}; border-radius: 3px;')
    return d


class EncodingHealthDialog(FramedDialog):
    """``exec()`` 返回 Accepted 且 ``self.convert`` 为真时 = 用户要「转换后推送」。"""

    def __init__(self, *, encoding_key: str, encoding_name: str, eol_key: str,
                 eol_name: str, parent=None) -> None:
        super().__init__('编码与换行符提醒', parent, icon_name='alert-circle',
                         width=460, icon_color=theme.WARNING)

        self.convert = False
        self._encoding_key = encoding_key
        self._encoding_name = encoding_name
        self._eol_key = eol_key
        self._eol_name = eol_name

        for text in reminder_lines(encoding_key, encoding_name, eol_key):
            self.body.addWidget(self._item(text))

        if needs_conversion(encoding_key):
            self.body.addWidget(label(
                f'「转换后推送」会把这篇以 UTF-8 重新存盘（内容一个字都不改），'
                f'然后开始推送。原文件会被覆盖，转换后记事本里打开显示正常。',
                theme.TEXT_FAINT, theme.FS_LABEL, wrap=True))

        self._btn_keep = self.add_ghost('保持原样')
        self._btn_keep.clicked.connect(self.reject)
        if needs_conversion(encoding_key):
            self._btn_convert = self.add_primary('转换后推送', 'push')
            self._btn_convert.clicked.connect(self._accept_convert)
        else:
            # 只有换行符一条时没什么可转的，给一个诚实的"知道了"
            self._btn_keep.setText('知道了')

        self.finish()

    # ───────────────────────── 内部 ─────────────────────────

    def _item(self, text: str) -> QFrame:
        """一条提醒：小圆点 + 一句说明。

        行高用 Qt 默认（设计稿写的是 17px）：这段文案最多两行，为它引一套
        富文本行高不值当，也会和项目里其它说明文字的基线对不齐。
        """
        row = QFrame()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        dot = _dot(theme.WARNING)
        lay.addWidget(dot, 0, Qt.AlignTop)
        lay.addWidget(label(text, theme.TEXT_SECOND, theme.FS_UI, wrap=True), 1)
        return row

    def _accept_convert(self) -> None:
        self.convert = True
        self.accept()
