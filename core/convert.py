# -*- coding: utf-8 -*-
"""txt → Markdown 真源（参数化版，逻辑源自 ``java-notes/tools/convert_txt.py``）。

转换规则**保持不变**，因为这是用户已经形成的书写习惯，改了就要重新适应：

    行首 ``===== 标题 =====``   ->  ``## 标题``          （章节）
    ``（一）小节名``            ->  ``### （一）小节名``  （小节）
    ``12：题目？``              ->  ``#### 12：题目？``   （题目）
    ``（跳过）19：题目？``      ->  ``#### （跳过）19：题目？``
    其余缩进行                  ->  去掉缩进，作为答案正文

规则细节（踩过坑，别动）：
* 只有**顶格**行才可能是章节 / 小节 / 题目；缩进行一律算答案正文
  （答案内部也会出现 ``1：`` ``2：`` 这类编号步骤）。
* 缩进判定要包含全角空格 ``\\u3000`` 与不换行空格 ``\\u00a0``。
* 换行如何渲染交给 ``site.py`` 统一处理，这里**不写入任何隐藏字符**。

新增：**三级编码探测**。用户用记事本写笔记，「另存为 ANSI」会变成 GBK，
原脚本硬编码 ``utf-8`` 会直接崩溃。
"""
from __future__ import annotations

import re
from pathlib import Path

CHAP_RE = re.compile(r'^=+\s*(.+?)\s*=+$')
SEC_RE = re.compile(r'^（[一二三四五六七八九十]+）[^：？]*$')
Q_RE = re.compile(r'^(\d+)：(.*)$')
QSKIP_RE = re.compile(r'^（跳过）\s*(\d+)：(.*)$')

# 判定用（多行）：只要出现「编号题目」即算
_Q_ANY_RE = re.compile(r'^\s*\d+：', re.M)

_INDENT_CHARS = ('\t', ' ', '\u3000', '\u00a0')


class NoteFormatError(ValueError):
    """笔记原文无法解析。"""


def read_text_auto(path: str | Path) -> tuple[str, str]:
    """读取文本并返回 ``(内容, 实际编码)``。

    依次尝试 ``utf-8-sig`` / ``utf-8`` / ``gbk``。``utf-8-sig`` 在前，
    这样带 BOM 的文件会顺带把 BOM 去掉，不会污染文档标题。
    """
    raw = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'gbk'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise NoteFormatError(f'无法识别文件编码（已试 utf-8-sig / utf-8 / gbk）：{path}')


def detect_mode(text: str) -> str:
    """判定笔记本体适合哪种发布模式。

    * ``site`` —— 有 ``===== 章 =====`` 标记且有编号题目，可以生成文档站；
    * ``raw``  —— 不满足上述条件，**降级为原样上传**，绝不报错。
    """
    if CHAP_RE.search(text) and _Q_ANY_RE.search(text):
        return 'site'
    return 'raw'


def convert(text: str) -> str:
    """把笔记原文转成 Markdown 真源。"""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out: list[str] = []
    title_done = False

    for raw in lines:
        stripped = raw.strip()

        # 空行：压成一个，保留段落间隔
        if not stripped:
            if out and out[-1] != '':
                out.append('')
            continue

        is_indented = raw[:1] in _INDENT_CHARS

        # 1) 文档标题 = 第一个非空行
        if not title_done:
            out.append(f'# {stripped}')
            out.append('')
            title_done = True
            continue

        # 2) 章节
        m = CHAP_RE.match(stripped)
        if m and not is_indented:
            if out and out[-1] != '':
                out.append('')
            out.append(f'## {m.group(1)}')
            out.append('')
            continue

        # 3) 小节
        if SEC_RE.match(stripped) and not is_indented:
            if out and out[-1] != '':
                out.append('')
            out.append(f'### {stripped}')
            out.append('')
            continue

        # 4) 题目
        m = QSKIP_RE.match(stripped) or Q_RE.match(stripped)
        if m and not is_indented:
            prefix = '（跳过）' if QSKIP_RE.match(stripped) else ''
            if out and out[-1] != '':
                out.append('')
            out.append(f'#### {prefix}{m.group(1)}：{m.group(2)}')
            out.append('')
            continue

        # 5) 答案正文：只去缩进
        out.append(stripped)

    while out and out[-1] == '':
        out.pop()

    return '\n'.join(out) + '\n'


def convert_to_file(src: str | Path, dst: str | Path) -> dict:
    """读取 txt、转换并写入 md，返回统计信息。"""
    text, encoding = read_text_auto(src)
    md = convert(text)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(md, encoding='utf-8', newline='\n')
    return {
        'encoding': encoding,
        'chapters': len(re.findall(r'^## ', md, re.M)),
        'sections': len(re.findall(r'^### ', md, re.M)),
        'questions': len(re.findall(r'^#### ', md, re.M)),
        'bytes': len(md.encode('utf-8')),
    }
