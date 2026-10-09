# -*- coding: utf-8 -*-
"""Markdown 真源 → docsify 站点（参数化版，逻辑源自 ``java-notes/tools/build.py``）。

产物：

    <docs>/README.md     首页（章节统计）
    <docs>/_sidebar.md   侧边栏目录
    <docs>/01.md ...     各章正文
    <docs>/index.html    docsify 入口（标题 / 描述参数化渲染）
    <docs>/assets/*      本地化的前端资源（离线可用，不依赖 CDN）
    <docs>/.nojekyll     让 GitHub Pages 跳过 Jekyll，保住 _sidebar.md

所有写文件都带 ``newline='\\n'``，与 ``.gitattributes`` 的 ``eol=lf`` 保持一致，
否则 Windows 上会写成 CRLF，每次提交都冒「LF will be replaced by CRLF」警告。
"""
from __future__ import annotations

import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSETS = PKG_ROOT / 'assets' / 'docsify'
DEFAULT_TEMPLATE = PKG_ROOT / 'templates' / 'index.html'

CHAPTER_RE = re.compile(r'^#### (.+)$')


def harden_breaks(lines: list[str]) -> list[str]:
    """答案块内的连续非空行转成 Markdown 硬换行（行尾补两个空格）。

    笔记习惯是「一行一个要点」，靠换行分条；但 Markdown 会把单个换行合并成一段。
    这件事交给构建脚本自动完成，真源里就不需要夹带任何隐藏字符。
    空行 = 真正的段落分隔，保持不动；标题行也不动。

    **代码围栏（````` ``` ````` / ``~~~``）内部不动** —— 否则那两个尾随空格
    会变成代码内容的一部分，把 Java 代码悄悄改掉。
    """
    out: list[str] = []
    fence = ''
    for ln in lines:
        s = ln.rstrip()
        head = s.lstrip()
        if head.startswith('```') or head.startswith('~~~'):
            marker = head[:3]
            if fence == '':
                fence = marker
            elif fence == marker:
                fence = ''
            out.append(s)
            continue
        if fence or not s or s.startswith('#'):
            out.append(s)
        else:
            out.append(s + '  ')
    return out


def parse(text: str, default_title: str = '笔记') -> tuple[str, list[dict]]:
    doc_title = default_title
    chapters: list[dict] = []
    cur = None
    for ln in text.replace('\r\n', '\n').split('\n'):
        if ln.startswith('# ') and not ln.startswith('##'):
            doc_title = ln[2:].strip()
            continue
        if ln.startswith('## '):
            cur = {'title': ln[3:].strip(), 'body': []}
            chapters.append(cur)
            continue
        if cur is not None:
            cur['body'].append(ln)
    return doc_title, chapters


def stats(chapter: dict) -> tuple[int, int]:
    """返回 ``(题目数, 已作答题数)``；题目下方只要有正文就算已作答。"""
    total = answered = 0
    pending_has_body = None
    for ln in chapter['body']:
        if CHAPTER_RE.match(ln):
            if pending_has_body:
                answered += 1
            total += 1
            pending_has_body = False
            continue
        s = ln.strip()
        if pending_has_body is not None and s and not s.startswith('#'):
            pending_has_body = True
    if pending_has_body:
        answered += 1
    return total, answered


def _write_if_changed(path: Path, text: str) -> bool:
    """内容不同才写盘；返回是否发生变化（避免制造无意义的提交）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode('utf-8')
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


def _sync_assets(src_dir: Path, dst_dir: Path) -> int:
    """把自带的前端资源同步到站点目录，返回实际更新的文件数。"""
    if not src_dir.is_dir():
        raise FileNotFoundError(f'找不到前端资源目录：{src_dir}')
    changed = 0
    for f in sorted(src_dir.iterdir()):
        if not f.is_file():
            continue
        dst = dst_dir / f.name
        data = f.read_bytes()
        if dst.exists() and dst.read_bytes() == data:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        changed += 1
    return changed


def _html_escape(s: str) -> str:
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _js_string(s: str) -> str:
    """把任意文本变成**带引号的** JS 字符串字面量（含引号转义与换行处理）。"""
    out = (str(s).replace('\\', '\\\\').replace("'", "\\'")
           .replace('\n', '\\n').replace('\r', ''))
    return f"'{out}'"


def render_index(title: str, desc: str, *, template_path: Path | None = None,
                 search_placeholder: str = '搜索笔记', name: str | None = None) -> str:
    """渲染 docsify 入口页。

    模板里的占位符分两种上下文，**不能一律直接替换**：
    ``{{TITLE}}`` / ``{{DESC}}`` 在 HTML 里（要转义 ``<`` ``&``），
    ``{{NAME}}`` / ``{{SEARCH_PLACEHOLDER}}`` 在 JS 里（要带引号并转义引号）。
    笔记标题是用户随手写的，这两种转义少一个就会把页面撑坏。
    """
    tpl = Path(template_path or DEFAULT_TEMPLATE).read_text(encoding='utf-8')
    return (tpl
            .replace('{{TITLE}}', _html_escape(title))
            .replace('{{DESC}}', _html_escape(desc))
            .replace('{{NAME}}', _js_string(name or title))
            .replace('{{SEARCH_PLACEHOLDER}}', _js_string(search_placeholder)))


def build(md_path: str | Path, docs_dir: str | Path, *, title: str | None = None,
          desc: str | None = None, assets_src: Path | None = None,
          template_path: Path | None = None, on_log=None) -> dict:
    """把 Markdown 真源构建成 docsify 站点，返回统计信息。"""
    log = on_log or (lambda *_a, **_k: None)
    md_path = Path(md_path)
    docs_dir = Path(docs_dir)

    if not md_path.exists():
        raise FileNotFoundError(f'找不到 Markdown 真源：{md_path}')

    doc_title, chapters = parse(md_path.read_text(encoding='utf-8'))
    if title:
        doc_title = title
    if not chapters:
        raise ValueError(f'真源里没有解析到任何「## 」章节：{md_path}')

    docs_dir.mkdir(parents=True, exist_ok=True)

    # 只清理上一轮生成的章节产物（01.md 这类数字命名），不碰其它任何文件
    for old in docs_dir.glob('[0-9][0-9].md'):
        old.unlink()

    sidebar = ['- [🏠 首页](/README.md)']
    index_rows: list[str] = []
    grand_total = grand_answered = 0
    changed = 0

    for i, ch in enumerate(chapters, start=1):
        fname = f'{i:02d}.md'
        body = '\n'.join(harden_breaks(ch['body'])).strip() + '\n'
        content = f'# {ch["title"]}\n\n' + body
        content = re.sub(r'\n{3,}', '\n\n', content)
        changed += _write_if_changed(docs_dir / fname, content)

        total, answered = stats(ch)
        grand_total += total
        grand_answered += answered

        sidebar.append(f'- [{i}. {ch["title"]}]({fname})')
        index_rows.append(f'| [{ch["title"]}]({fname}) | {total} | {answered} |')

    changed += _write_if_changed(docs_dir / '_sidebar.md', '\n'.join(sidebar) + '\n')

    home = [
        f'# {doc_title}',
        '',
        '> 面试复习题库 · 纯文本单一真源，构建产物自动生成',
        '',
        f'**{len(chapters)} 个章节 · {grand_total} 道题目 · 已作答 {grand_answered} 道'
        f' · 待作答 {grand_total - grand_answered} 道**',
        '',
        '| 章节 | 题目数 | 已作答 |',
        '| :--- | ---: | ---: |',
        *index_rows,
        f'| **合计** | **{grand_total}** | **{grand_answered}** |',
        '',
        '---',
        '',
        '手机上点左上角 ☰ 展开目录、点右上角 🔍 搜索题目；表格里的章节名可直接点开。',
        '',
    ]
    changed += _write_if_changed(docs_dir / 'README.md', '\n'.join(home))

    changed += _write_if_changed(docs_dir / '.nojekyll', '')
    changed += _sync_assets(Path(assets_src or DEFAULT_ASSETS), docs_dir / 'assets')
    changed += _write_if_changed(
        docs_dir / 'index.html',
        render_index(doc_title, desc or f'{doc_title} · 在线阅读', template_path=template_path),
    )

    log(f'站点已构建：{docs_dir}（章节 {len(chapters)} 个，'
        f'题目 {grand_total} 道，已作答 {grand_answered} 道）')
    return {
        'chapters': len(chapters),
        'questions': grand_total,
        'answered': grand_answered,
        'files_changed': changed,
    }


# ═══════════════════════════════════════════════════════════════════
# 通用构建器：一个 txt 一页
# ═══════════════════════════════════════════════════════════════════
#
# 上面的 build() 是给「单个 md、按 ## 分章」的题库写的，只有那种形状的笔记能用。
# FreePushNote 是通用 txt 工具，一个分组里可能躺着十几篇互不相干的随笔，
# 所以这里再给一个通用构建器：**一篇笔记 = 一个页面**，侧栏列文件名。
#
# 两者不冲突：命中「===== 章 ===== + 编号题目」的文件仍由 convert() 展开成章节，
# 页内照常有多级标题；其余笔记原样成页，不被改写。

#: 与站点自身的文件名冲突的 slug（撞了要加前缀，否则会覆盖首页）
RESERVED_SLUGS = {'readme', '_sidebar', 'index', 'assets', 'nojekyll'}

#: Windows 不允许出现在文件名里的字符（站点文件也要能落在 Windows 上）
_BAD_FILE_CHARS = re.compile(r'[#?%&=+<>:"|*\\/\s]+')


def page_slug(source_name: str, used: set[str]) -> str:
    """由原始文件名派生一个安全、稳定、不重复的页面 slug。

    * 保留中文（可读性优先，GitHub Pages 对 UTF-8 路径没问题）
    * 去掉 Windows 禁用的字符与 URL 里有特殊含义的 ``# ? % &``
    * 撞上站点自身文件名（README / index / …）时加前缀
    """
    stem = Path(str(source_name)).stem
    s = _BAD_FILE_CHARS.sub('-', stem).strip('-. ')
    if not s:
        s = 'page'
    if s.lower() in RESERVED_SLUGS:
        s = f'note-{s}'
    base, n = s, 2
    while s in used:
        s = f'{base}-{n}'
        n += 1
    used.add(s)
    return s


def build_notes_site(pages: list[dict], out_dir: str | Path, *,
                     title: str, desc: str | None = None,
                     assets_src: Path | None = None,
                     template_path: Path | None = None, on_log=None) -> dict:
    """把若干篇笔记构建成一个 docsify 站点。

    ``pages`` 形如 ``[{'source': '并发编程.txt', 'title': '并发编程',
    'markdown': '...'}]`` —— ``markdown`` 是已经准备好的正文
    （是否经过 :mod:`core.convert` 由调用方决定）。

    产出（全部在 ``out_dir`` 下）::

        index.html      docsify 入口
        README.md       首页：笔记清单 + 字数统计
        _sidebar.md     侧栏目录
        <slug>.md       每篇笔记一页
        .nojekyll       让 GitHub Pages 跳过 Jekyll（否则 _sidebar.md 会被吃掉）
        assets/*        本地化的前端资源
    """
    log = on_log or (lambda *_a, **_k: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    sidebar = ['- [首页](/README.md)']
    rows: list[str] = []
    total_chars = total_lines = changed = 0

    for page in pages:
        source = str(page.get('source') or 'note.txt')
        page_title = str(page.get('title') or Path(source).stem)
        body = str(page.get('markdown') or '').lstrip()
        if not body.startswith('#'):
            body = f'# {page_title}\n\n{body}'
        body = re.sub(r'\n{3,}', '\n\n', body).rstrip() + '\n'

        slug = page_slug(source, used)
        changed += _write_if_changed(out_dir / f'{slug}.md', body)

        chars = len(body)
        lines = body.count('\n')
        total_chars += chars
        total_lines += lines

        sidebar.append(f'- [{page_title}]({slug}.md)')
        rows.append(f'| [{page_title}]({slug}.md) | {chars} | {lines} |')

    changed += _write_if_changed(out_dir / '_sidebar.md', '\n'.join(sidebar) + '\n')

    home_lines = [f'# {title}', '']
    if desc:
        home_lines += [f'> {desc}', '']
    home_lines += [
        f'**{len(pages)} 篇笔记 · 共 {total_chars} 字 · {total_lines} 行**',
        '',
        '| 笔记 | 字数 | 行数 |',
        '| :--- | ---: | ---: |',
        *rows,
        '',
        '---',
        '',
        '手机上点左上角展开目录、点右上角搜索；表格里的笔记名可以直接点开。',
        '',
    ]
    changed += _write_if_changed(out_dir / 'README.md', '\n'.join(home_lines))

    changed += _write_if_changed(out_dir / '.nojekyll', '')
    changed += _sync_assets(Path(assets_src or DEFAULT_ASSETS), out_dir / 'assets')
    changed += _write_if_changed(
        out_dir / 'index.html',
        render_index(title, desc or f'{title} · 在线阅读',
                     template_path=template_path),
    )

    log(f'站点已构建：{out_dir}（{len(pages)} 篇，共 {total_chars} 字）')
    return {
        'pages': len(pages),
        'chars': total_chars,
        'lines': total_lines,
        'files_changed': changed,
    }
