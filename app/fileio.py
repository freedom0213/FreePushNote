# -*- coding: utf-8 -*-
"""纯文本读写：编码与换行符探测。

Windows 上用记事本存过的 txt 可能是 UTF-8 / UTF-8 with BOM / GBK（ANSI），
换行符可能是 CRLF 或 LF。这两件事都直接影响推送结果：

* **非 UTF-8** → 推到 GitHub 网页上是乱码
* **CRLF** → 仓库里出现「幽灵 diff」（本地没改，仓库却显示每行都改了）

策略是：**本地文件原样读写、不动它**；状态栏如实显示实际编码与换行符；
推送时把副本统一转成 UTF-8 + LF 再写进工作区。
"""
from __future__ import annotations

import os
from pathlib import Path

BOM_UTF8 = b'\xef\xbb\xbf'
BOM_UTF16_LE = b'\xff\xfe'
BOM_UTF16_BE = b'\xfe\xff'

# 编码 → 状态栏显示名
DISPLAY_NAME = {
    'utf-8': 'UTF-8',
    'utf-8-sig': 'UTF-8 BOM',
    'utf-16-le': 'UTF-16 LE',
    'utf-16-be': 'UTF-16 BE',
    'gb18030': 'GBK',
    'big5': 'Big5',
}


def sniff_encoding(raw: bytes) -> tuple[str, bool]:
    """返回 ``(encoding, 是否有 BOM)``。逐级降级，永远给得出一个答案。"""
    if raw.startswith(BOM_UTF8):
        return 'utf-8-sig', True
    if raw.startswith(BOM_UTF16_LE):
        return 'utf-16-le', True
    if raw.startswith(BOM_UTF16_BE):
        return 'utf-16-be', True

    try:
        raw.decode('utf-8')
        return 'utf-8', False
    except UnicodeDecodeError:
        pass

    # gb18030 是 GBK 的超集，能覆盖绝大多数中文 ANSI 文件
    for enc in ('gb18030', 'big5'):
        try:
            raw.decode(enc)
            return enc, False
        except UnicodeDecodeError:
            continue

    return 'utf-8', False        # 兜底：按 UTF-8 尽力解（errors='replace'）


def detect_eol(text: str) -> str:
    """返回 ``'crlf'`` / ``'lf'`` / ``'cr'``。以出现次数最多的为准。"""
    crlf = text.count('\r\n')
    cr = text.count('\r') - crlf
    lf = text.count('\n') - crlf
    if crlf and crlf >= max(cr, lf):
        return 'crlf'
    if lf and lf >= cr:
        return 'lf'
    if cr:
        return 'cr'
    return 'crlf'                # 单行无换行的文件：按 Windows 习惯当作 CRLF


EOL_DISPLAY = {'crlf': 'CRLF', 'lf': 'LF', 'cr': 'CR'}


def read_text(path: str | Path) -> tuple[str, str, str]:
    """读取文本。返回 ``(正文, 编码, 换行符)``，备注：正文中的换行已统一成 ``\\n``。"""
    raw = Path(path).read_bytes()
    enc, _bom = sniff_encoding(raw)
    text = raw.decode(enc, errors='replace')
    eol = detect_eol(text)
    # 统一成 \n 交给编辑器，避免 QPlainTextEdit 把 \r 当成可见字符
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text, enc, eol


def is_probably_text(path: str | Path, probe: int = 4096) -> bool:
    """粗判是否是可编辑的纯文本（前 4KB 里没有 NUL 就认为是）。"""
    try:
        chunk = Path(path).read_bytes()[:probe]
    except OSError:
        return False
    return b'\x00' not in chunk


def write_text(path: str | Path, text: str, encoding: str = 'utf-8',
               eol: str = 'crlf') -> Path:
    """原子写入文本（临时文件 + ``os.replace``）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = text.replace('\r\n', '\n')
    if eol == 'crlf':
        data = data.replace('\n', '\r\n')

    raw = data.encode(encoding)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return p


def to_repo_bytes(text: str, encoding: str = 'utf-8') -> bytes:
    """转成「要写进仓库」的字节：UTF-8 编码 + LF 换行（与 .gitattributes 一致）。"""
    data = text.replace('\r\n', '\n')
    if encoding == 'utf-8-sig':
        return data.encode('utf-8')          # 仓库里不留 BOM
    return data.encode('utf-8')
