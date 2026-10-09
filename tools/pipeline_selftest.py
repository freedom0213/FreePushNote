# -*- coding: utf-8 -*-
"""推送链路自测：用**本地 bare 仓库**当远端，跑完整个真实流程。

这不是模拟 —— git init / add / commit / push 全都是真的，只是远端换成
本地目录（``file://``），所以不联网、不碰任何真实 GitHub 仓库。

这样能把除「网络 + GitHub 认证」之外的全部环节验掉：

* 白名单是否真的生效（没勾选的文件**物理上进不了工作区**）
* 用户笔记文件夹里有没有被塞进 ``.git``
* txt → Markdown（章节模式 / 普通笔记两种）
* 站点产物是否齐全、侧栏与首页内容是否正确
* 取消勾选后，文件是否真的从仓库里消失
* 令牌凭据助手是否真能把令牌交给 git（``git credential fill`` 验证）
* 内容没变时是否识别为「没有改动」而不是制造空提交

用法：
    .venv\\Scripts\\python.exe tools\\pipeline_selftest.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在导入 core.config 之前重定向，否则会动到真实用户目录
_TMP = Path(tempfile.mkdtemp(prefix='pushnote_pipeline_test_'))
os.environ['PUSHNOTE_HOME'] = str(_TMP)

from core import config, convert, gitops, pipeline, site  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = '') -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ok   {name}')
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f'  FAIL {name}  {extra}')


# ───────────────────────── 素材 ─────────────────────────

CHAPTER_TXT = """Java 八股文笔记

===== 集合 =====

1：ArrayList 和 LinkedList 的区别？

  底层结构不同：一个是数组，一个是双向链表。
  所以随机访问和中间插入的性能表现相反。

2：HashMap 的扩容机制？

  容量到达阈值就翻倍，并把元素重新分布。

===== 并发 =====

3：synchronized 和 ReentrantLock 的区别？

  前者由 JVM 管理、自动释放；后者需要手动 unlock，但支持公平锁。
"""

PLAIN_TXT = """今天的读书笔记

第一行要点：记忆不是录像带，更像一次次重写。
第二行要点：每回想一次，就覆盖一次旧的痕迹。

第三段：留白是段落分隔，不该被合并。
"""

CODE_TXT = """代码片段测试

普通一行。

```java
public class A {
    int x = 1;
}
```

围栏之后的一行。
"""

LATIN_TXT = """Mixed note

alpha
beta
"""


def build_source_folder(root: Path) -> Path:
    folder = root / '笔记文件夹'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'Java八股.txt').write_text(CHAPTER_TXT, encoding='utf-8', newline='\r\n')
    (folder / '读书笔记.txt').write_text(PLAIN_TXT, encoding='utf-8', newline='\n')
    (folder / '代码片段.txt').write_text(CODE_TXT, encoding='utf-8', newline='\n')
    (folder / 'Mixed Note.txt').write_text(LATIN_TXT, encoding='utf-8')
    # GBK 编码：Windows 记事本「另存为 ANSI」的产物，必须能读、且仓库侧转 UTF-8
    (folder / '编码测试.txt').write_bytes('中文编码测试\n第二行\n'.encode('gbk'))
    # ★ 没被勾选的文件：绝不能出现在工作区或仓库里
    (folder / '密码备份.txt').write_text('不该上传的内容', encoding='utf-8')
    (folder / '照片说明.md').write_text('# 也不该上传', encoding='utf-8')
    # 不是笔记扩展名：连候选都不算
    (folder / 'key.txt.bak').write_text('backup', encoding='utf-8')
    return folder


def make_group(folder: Path, repo: str) -> dict:
    g = config.new_group(folder)
    g['id'] = 'notes'
    g['repo'] = repo
    g['branch'] = 'main'
    g['site'] = True
    g['site_title'] = '我的笔记'
    g['files'] = ['Java八股.txt', '读书笔记.txt', '代码片段.txt',
                  'Mixed Note.txt', '编码测试.txt']
    return g


def bare_tree(bare: Path) -> list[str]:
    # core.quotepath=false：否则 git 会把中文路径转义成 "\346\226\207..." 形式，
    # 断言会全部误判（这也是 main 仓库里 init_repo 要设它的原因）
    r = gitops.git(bare, '-c', 'core.quotepath=false',
                   'ls-tree', '-r', '--name-only', 'HEAD', check=False)
    return [l for l in gitops.stdout_of(r).splitlines() if l.strip()]


def bare_show(bare: Path, path: str) -> str:
    r = gitops.git(bare, '-c', 'core.quotepath=false', 'show', f'HEAD:{path}',
                   check=False)
    return gitops.stdout_of(r)


# ───────────────────────── 1. 白名单与隔离 ─────────────────────────

def test_config_model(folder: Path) -> None:
    print('\n[1] 配置模型（文件夹 = 分组 = 仓库）')

    cfg = config.blank_config()
    check('blank_config 结构为 v2',
          set(cfg) == {'version', 'defaults', 'groups'} and cfg['version'] == 2)

    g = make_group(folder, 'someone/demo-notes')
    config.upsert_group(cfg, g)
    check('合法分组无校验错误', config.validate_group(g, cfg) == [])

    check('非绝对路径的 folder 被拒',
          any('绝对路径' in e for e in
              config.validate_group({**g, 'folder': '笔记文件夹'})))
    check('不存在的 folder 被拒',
          any('不存在' in e for e in
              config.validate_group({**g, 'folder': str(folder / '不存在')})))

    check('文件名带路径分隔符被拒',
          any('分隔符' in e for e in
              config.validate_group({**g, 'files': ['../外面.txt']})))
    check('非文本扩展名被拒',
          any('只能纳入' in e for e in
              config.validate_group({**g, 'files': ['a.png']})))
    check('repo 格式被校验',
          any('owner/name' in e for e in
              config.validate_group({**g, 'repo': 'nope'})))

    # 同一文件夹 / 同一仓库不能重复绑定
    dup_folder = config.blank_config()
    config.upsert_group(dup_folder, g)
    other = make_group(folder, 'someone/other-repo')
    other['id'] = 'second'
    config.upsert_group(dup_folder, other)
    check('同一文件夹绑两次被拒',
          any('文件夹已属于' in e for e in config.validate_group(other, dup_folder)))

    dup_repo = config.blank_config()
    config.upsert_group(dup_repo, g)
    third = make_group(folder.parent / '另一个文件夹', 'someone/demo-notes')
    (folder.parent / '另一个文件夹').mkdir(exist_ok=True)
    third['id'] = 'third'
    config.upsert_group(dup_repo, third)
    check('同一仓库绑两次被拒',
          any('已被分组' in e for e in config.validate_group(third, dup_repo)))

    # 归属查询
    cfg2 = config.blank_config()
    config.upsert_group(cfg2, make_group(folder, 'someone/demo-notes'))
    check('group_for_path 命中子文件',
          (config.group_for_path(cfg2, folder / '读书笔记.txt') or {}).get('id') == 'notes')
    check('group_for_path 不误吞外部文件',
          config.group_for_path(cfg2, folder.parent / '别处.txt') is None)
    check('is_managed 认白名单内的文件',
          config.is_managed(cfg2, folder / '读书笔记.txt'))
    check('is_managed 拒绝白名单外的文件',
          not config.is_managed(cfg2, folder / '密码备份.txt'))

    check('scan_notes 只返回文本类',
          config.scan_notes(folder) == sorted(
              ['Java八股.txt', '读书笔记.txt', '代码片段.txt', 'Mixed Note.txt',
               '编码测试.txt', '密码备份.txt', '照片说明.md'],
              key=str.lower))
    check('detect_new_files 找出未纳管的',
          set(pipeline.detect_new_files(make_group(folder, 'x/y'))) ==
          {'密码备份.txt', '照片说明.md'})

    check('make_group_id 生成 slug',
          config.make_group_id(config.blank_config(), 'Java八股') == 'java')
    check('make_group_id 避免重复', (lambda c: (
        config.upsert_group(c, {**g, 'id': 'notes'}),
        config.make_group_id(c, 'notes') == 'notes-2')[1])(config.blank_config()))

    # v1 数据要被丢弃并留痕，而不是静默转换
    v1 = _TMP / 'v1.json'
    v1.write_text('{"version":1,"bindings":[{"id":"a"}],"active_id":"a"}',
                  encoding='utf-8')
    loaded = config.load(v1)
    check('v1 的 bindings 被丢弃', 'bindings' not in loaded)
    check('v1 丢弃数量被记录', loaded.get('_dropped_v1_bindings') == 1)
    check('_ 开头的内部字段不落盘',
          '_dropped_v1_bindings' not in
          config.save(loaded, _TMP / 'out.json').read_text(encoding='utf-8'))


# ───────────────────────── 2. 转换与站点 ─────────────────────────

def test_render(folder: Path) -> None:
    print('\n[2] 转换与站点构建')

    text = (folder / 'Java八股.txt').read_text(encoding='utf-8')
    check('识别为章节模式', convert.detect_mode(text) == 'site')
    md = convert.convert(text)
    check('章节转成 ##', '## 集合' in md)
    check('题目转成 ####', '#### 1：ArrayList' in md)

    # ── CRLF 回归 ──
    # Windows 记事本写出来的 txt 全是 CRLF。read_text_auto 是 read_bytes + 手工
    # decode，没有通用换行转换；一旦漏掉归一化，以 ^...$ 匹配行结构的正则
    # （CHAP_RE）就全部失效，整篇降级成原样上传 —— 这个 bug 真的发生过。
    crlf_src = _TMP / 'crlf_样本.txt'
    crlf_src.write_bytes(CHAPTER_TXT.replace('\n', '\r\n').encode('utf-8'))
    crlf_text, _enc = convert.read_text_auto(crlf_src)
    check('read_text_auto 把 CRLF 归一成 LF', '\r' not in crlf_text)
    check('CRLF 文本仍能识别为章节模式', convert.detect_mode(crlf_text) == 'site')
    check('detect_mode 自身也容错 CRLF',
          convert.detect_mode(CHAPTER_TXT.replace('\n', '\r\n')) == 'site')
    check('CRLF 文本转换结果与 LF 一致',
          convert.convert(crlf_text) == convert.convert(CHAPTER_TXT))

    plain = (folder / '读书笔记.txt').read_text(encoding='utf-8')
    check('普通笔记识别为 raw', convert.detect_mode(plain) == 'raw')
    body = pipeline._plain_note_to_md(plain)
    check('普通笔记：单换行变硬换行', '第一行要点' in body and '  \n第二行要点' in body)
    check('普通笔记：空行保持为段落分隔', '\n\n第三段' in body)

    code = (folder / '代码片段.txt').read_text(encoding='utf-8')
    code_md = pipeline._plain_note_to_md(code)
    check('代码围栏内部不被补尾随空格', '    int x = 1;\n' in code_md)
    check('代码围栏外的行仍然硬换行', '普通一行。  \n' in code_md)

    # slug 卫生
    used: set[str] = set()
    check('slug 保留中文', site.page_slug('读书笔记.txt', used) == '读书笔记')
    check('slug 处理空格', site.page_slug('Mixed Note.txt', used) == 'Mixed-Note')
    check('slug 撞上站点文件名时加前缀',
          site.page_slug('README.txt', used) == 'note-README')
    check('slug 遇到非法字符', site.page_slug('a#b?c%d.txt', used) == 'a-b-c-d')
    check('slug 去重', site.page_slug('读书笔记.md', used) == '读书笔记-2')
    check('slug 全非法字符时兜底', site.page_slug('???.txt', used) == 'page')
    # 全角问号在 Windows 上是合法文件名字符，应当保留（不能误删中文标点）
    check('slug 保留全角标点', site.page_slug('标题？.txt', used) == '标题？')

    # 模板渲染的两种转义上下文
    html = site.render_index('带 <script> 的标题', '说明 & 更多', name="it's")
    check('HTML 上下文被转义',
          '带 &lt;script&gt; 的标题' in html and '<script> 的标题' not in html)
    check('JS 上下文带引号并转义', "name: 'it\\'s'," in html)


# ───────────────────────── 3. 凭据助手 ─────────────────────────

def test_credential_helper() -> None:
    print('\n[3] 令牌凭据助手')

    helper = gitops.token_helper()
    check('助手从环境变量读密码', gitops.TOKEN_ENV_VAR in helper)
    check('用户名用 x-access-token', gitops.TOKEN_USERNAME in helper)
    check('默认不把令牌放进命令行参数',
          all('secret' not in a for a in gitops.credential_args('secret-token-xyz')))

    # 真的问一次 git：让它用我们的助手把凭据吐出来
    env = os.environ.copy()
    env[gitops.TOKEN_ENV_VAR] = 'gho_TOKEN_FOR_TEST'
    import subprocess
    proc = subprocess.run(
        ['git', *gitops.credential_args('gho_TOKEN_FOR_TEST'), 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n',
        capture_output=True, text=True, encoding='utf-8', env=env, timeout=30,
    )
    out = proc.stdout or ''
    check('git 能通过助手拿到令牌', 'password=gho_TOKEN_FOR_TEST' in out,
          f'退出码 {proc.returncode}，输出 {out!r} {proc.stderr!r}')
    check('git 能通过助手拿到用户名',
          f'username={gitops.TOKEN_USERNAME}' in out)

    name, email = gitops.identity_for_account('freedom0213', 184794503)
    check('提交身份用 noreply 邮箱',
          email == '184794503+freedom0213@users.noreply.github.com')
    check('提交身份不含真实邮箱', '@gmail' not in email and '@qq' not in email)


# ───────────────────────── 4. 完整推送 ─────────────────────────

def test_full_push(folder: Path, bare: Path) -> None:
    print('\n[4] 完整推送（本地 bare 仓库当远端）')

    group = make_group(folder, 'someone/demo-notes')

    # 把 ensure_remote 换成指向本地 bare —— 这是唯一被替换的一步，
    # 其余全是真实 git 操作
    def local_remote(path, repo, on_log=None):
        url = bare.as_uri()
        if gitops.remote_url(path) != url:
            gitops.git(path, 'remote', 'remove', 'origin', check=False)
            gitops.git(path, 'remote', 'add', 'origin', url)
        return url

    real_ensure = gitops.ensure_remote
    gitops.ensure_remote = local_remote
    try:
        logs: list[str] = []
        result = pipeline.push_group(group, message='首次推送测试',
                                     token='fake-token-not-used-for-file-remote',
                                     account={'login': 'freedom0213', 'id': 184794503},
                                     retries=1, on_log=logs.append)

        check('首次推送成功', result.ok, f'{result.reason} / {result.message} / {result.detail}')
        check('拿到了提交短哈希', bool(result.commit))
        check('没有 git 报错', result.reason == pipeline.REASON_OK, result.detail)

        tree = bare_tree(bare)
        check('远端有笔记原文', 'Java八股.txt' in tree)
        check('远端有站点入口', 'index.html' in tree)
        check('远端有侧栏目录', '_sidebar.md' in tree)
        check('远端有首页', 'README.md' in tree)
        check('远端有 .nojekyll', '.nojekyll' in tree)
        check('远端有本地化的前端资源',
              any(t.startswith('assets/') and t.endswith('docsify.min.js') for t in tree))
        check('章节模式的笔记生成了页面', 'Java八股.md' in tree)
        check('普通笔记生成了页面', '读书笔记.md' in tree)
        check('中文以外的文件名也安全', 'Mixed-Note.md' in tree)

        # ★ 关键安全断言
        check('未勾选的文件不在远端', '密码备份.txt' not in tree)
        check('未勾选的 md 不在远端', '照片说明.md' not in tree)
        check('非笔记扩展名不在远端', 'key.txt.bak' not in tree)

        # 用户文件夹没被污染
        check('用户文件夹里没有 .git', not (folder / '.git').exists())
        check('用户文件夹里没有多出生成物',
              sorted(p.name for p in folder.iterdir()) ==
              sorted(['Java八股.txt', '读书笔记.txt', '代码片段.txt', 'Mixed Note.txt',
                      '编码测试.txt', '密码备份.txt', '照片说明.md', 'key.txt.bak']))

        # 内容正确性
        sidebar = bare_show(bare, '_sidebar.md')
        check('侧栏列出所有笔记', all(n in sidebar for n in
                                    ['Java八股', '读书笔记', '代码片段', 'Mixed-Note']))
        check('侧栏第一项是首页', sidebar.splitlines()[0].endswith('/README.md)'))

        page = bare_show(bare, 'Java八股.md')
        check('章节笔记页里有 ## 章节', '## 集合' in page,
              f'读到 {len(page)} 字符：{page[:80]!r}')
        check('章节笔记页里有 #### 题目', '#### 1：ArrayList' in page,
              f'读到 {len(page)} 字符：{page[:80]!r}')

        plain_page = bare_show(bare, '读书笔记.md')
        check('普通笔记页保留硬换行', '第一行要点' in plain_page and '  ' in plain_page)

        readme = bare_show(bare, 'README.md')
        check('首页有篇数统计', '5 篇笔记' in readme)

        # GBK 文件在仓库里是 UTF-8
        gbk = bare_show(bare, '编码测试.txt')
        check('GBK 文件在仓库里已转 UTF-8', '中文编码测试' in gbk)
        check('编码转换有提醒', any('编码' in w for w in result.warnings))

        # 提交信息与作者
        author = gitops.stdout_of(gitops.git(bare, 'log', '-1', '--format=%an <%ae>'))
        check('提交归属到 GitHub 账号',
              'freedom0213' in author and 'users.noreply.github.com' in author, author)
        subject = gitops.stdout_of(gitops.git(bare, 'log', '-1', '--format=%s'))
        check('提交信息用的是用户填的那句', subject == '首次推送测试', subject)

        # ── 内容没变时不该制造空提交
        result2 = pipeline.push_group(group, token='x', retries=1,
                                      account={'login': 'freedom0213', 'id': 1},
                                      on_log=lambda *_a: None)
        check('内容未变识别为“无需推送”',
              result2.reason == pipeline.REASON_NO_CHANGES,
              f'{result2.reason} / {result2.message}')
        commits = gitops.stdout_of(gitops.git(bare, 'log', '--oneline')).splitlines()
        check('没有产生多余的提交', len(commits) == 1, f'实际 {len(commits)} 个')

        # ── 取消勾选 → 文件应真的从仓库消失
        group['files'] = [n for n in group['files'] if n != '代码片段.txt']
        result3 = pipeline.push_group(group, message='移除一个文件', token='x', retries=1,
                                      account={'login': 'freedom0213', 'id': 1},
                                      on_log=lambda *_a: None)
        check('取消勾选后推送成功', result3.ok, result3.detail)
        tree3 = bare_tree(bare)
        check('被取消勾选的文件已从远端消失', '代码片段.txt' not in tree3)
        check('取消勾选后站点也同步移除', '代码片段.md' not in tree3)
        check('其余笔记仍在', '读书笔记.txt' in tree3)

        # ── 只推子集（设计稿 S-01 的勾选）
        result4 = pipeline.push_group(
            group, message='只推一篇', names=['读书笔记.txt'], token='x', retries=1,
            account={'login': 'freedom0213', 'id': 1}, on_log=lambda *_a: None)
        check('只推子集能成功', result4.ok, result4.detail)
        tree4 = bare_tree(bare)
        check('子集推送后另外的文件也从工作区消失（符合“清空重建”语义）',
              'Java八股.txt' not in tree4 and '读书笔记.txt' in tree4)

        # ── 失败路径
        empty = pipeline.push_group({**group, 'files': []}, token='x',
                                    on_log=lambda *_a: None)
        check('空白名单 → no_files', empty.reason == pipeline.REASON_NO_FILES)

        no_token = pipeline.push_group(group, token=None, on_log=lambda *_a: None)
        check('没令牌 → 拒绝推送', no_token.reason == pipeline.REASON_NO_REMOTE,
              no_token.reason)

        no_repo = pipeline.push_group({**group, 'repo': ''}, token='x',
                                      on_log=lambda *_a: None)
        check('没仓库 → 拒绝推送', no_repo.reason == pipeline.REASON_NO_REMOTE)

        ghost = pipeline.push_group({**group, 'files': ['不存在的文件.txt']},
                                    token='x', on_log=lambda *_a: None)
        check('文件全读不到 → no_files 并带警告',
              ghost.reason == pipeline.REASON_NO_FILES and bool(ghost.warnings))
    finally:
        gitops.ensure_remote = real_ensure


def test_bare_guard() -> None:
    print('\n[5] 删除操作的安全闸')
    for evil in (_TMP, config.CONFIG_DIR, Path.home()):
        try:
            pipeline.clear_workspace(evil)
        except ValueError:
            check(f'拒绝清空工作区之外的路径：{evil}', True)
        else:
            check(f'拒绝清空工作区之外的路径：{evil}', False, '竟然允许了！')

    ws = config.workspace_dir({'id': 'ok'})
    ws.mkdir(parents=True, exist_ok=True)
    (ws / 'junk.txt').write_text('x', encoding='utf-8')
    pipeline.clear_workspace(ws)
    check('工作区内部可以正常清空', not (ws / 'junk.txt').exists())


def main() -> int:
    print('=' * 66)
    print('FreePushNote 推送链路自测（本地 bare 仓库，不联网）')
    print('=' * 66)
    print(f'临时目录：{_TMP}')

    folder = build_source_folder(_TMP)
    test_config_model(folder)
    test_render(folder)
    test_credential_helper()

    bare = _TMP / 'remote.git'
    bare.mkdir(parents=True, exist_ok=True)
    subprocess_init = gitops.git(bare, 'init', '--bare', '-b', 'main', check=False)
    assert subprocess_init.returncode == 0, subprocess_init
    test_full_push(folder, bare)
    test_bare_guard()

    print('\n' + '=' * 66)
    print(f'通过 {PASS} / {PASS + FAIL}')
    if FAILURES:
        print('失败项：')
        for n in FAILURES:
            print(f'  - {n}')
    print('=' * 66)

    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())
