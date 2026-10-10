# -*- coding: utf-8 -*-
"""纯文本读写（编辑器侧入口）。

实现已经下沉到 :mod:`core.textio` —— **Pull 也要用它**（把远端内容写回笔记
文件时必须保持原编码与原换行），而 core 不能反过来依赖界面层。
这里只做转发，调用点（``window`` / ``editor``）不必改。
"""
from __future__ import annotations

from core.textio import (BOM_UTF16_BE, BOM_UTF16_LE,  # noqa: F401
                         BOM_UTF8, DISPLAY_NAME, EOL_DISPLAY, detect_eol,
                         is_probably_text, read_text, sniff_encoding,
                         to_repo_bytes, write_text)

__all__ = [
    'BOM_UTF8', 'BOM_UTF16_LE', 'BOM_UTF16_BE',
    'DISPLAY_NAME', 'EOL_DISPLAY',
    'sniff_encoding', 'detect_eol', 'read_text', 'write_text',
    'is_probably_text', 'to_repo_bytes',
]
