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
import subprocess
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


def push_and_remember(group: dict, **kwargs):
    """推送，并像界面那样记住「本工具产出的路径」（对应 ``window._remember_pushed``）。

    🔴 这份记录是**删除权限的唯一来源**：没有它，这次提交里所有"删除"都会被
    当成"仓库里的外来文件"而保住（保守方向）。真实流程里由界面在推送成功后
    写进分组配置，这里手动补上，好让"取消勾选 → 从仓库消失"这条设计意图
    仍然被测试覆盖。
    """
    result = pipeline.push_group(group, **kwargs)
    if result.ok and result.produced:
        group['pushed_paths'] = list(result.produced)
    return result


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

    # ── S-02：新文件提示要的「带时间 + 排除已忽略」──
    g_new = make_group(folder, 'x/y')
    fresh = pipeline.new_files(g_new)
    check('new_files 带上文件与修改时间',
          {f['name'] for f in fresh} == {'密码备份.txt', '照片说明.md'}
          and all(float(f['mtime']) > 0 for f in fresh),
          str(fresh)[:140])
    check('旧配置没有 ignored 字段时不报错',
          config.ignored_names({'files': ['a.txt']}) == [])

    cfg3 = config.blank_config()
    config.upsert_group(cfg3, g_new)
    check('add_ignored 写入并可读回',
          (config.add_ignored(cfg3, 'notes', ['密码备份.txt']) or {}).get('ignored')
          == ['密码备份.txt'])
    check('add_ignored 去重且保持顺序',
          (config.add_ignored(cfg3, 'notes',
                              ['密码备份.txt', '照片说明.md']) or {}).get('ignored')
          == ['密码备份.txt', '照片说明.md'])
    check('被忽略的文件不再出现在 new_files',
          pipeline.new_files(g_new) == [])
    check('add_ignored 对不存在的分组返回 None',
          config.add_ignored(cfg3, 'nope', ['x.txt']) is None)
    check('忽略的文件仍可能在白名单里（两件事互不干扰）',
          config.managed_names(g_new) and
          config.ignored_names(g_new) == ['密码备份.txt', '照片说明.md'])

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
        result = push_and_remember(group, message='首次推送测试',
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

        # ── 两阶段 API：stage 之后能读出真实的逐文件增删行数
        #    （界面靠它给出 S-01 弹层里的「3 个文件 · +23 −8」）
        (folder / '读书笔记.txt').write_text(
            PLAIN_TXT + '\n后来补的一行。\n', encoding='utf-8')
        staged = pipeline.stage_group(group, account={'login': 'freedom0213', 'id': 1},
                                      on_log=lambda *_a: None)
        check('stage_group 成功', staged.ok, staged.detail)
        # reason 的默认值是 REASON_GIT_ERROR（给失败结果兜底），成功路径漏传
        # 就会变成「ok=True 但 reason=git_error」—— 字段说谎最难查
        check('成功时 reason 是 ok（不是默认的 git_error）',
              staged.reason == pipeline.REASON_OK, staged.reason)
        check('stage 不过网也不提交（has_changes 只表示“有东西要推”）',
              staged.has_changes and bool(staged.workspace))
        row = next((c for c in staged.changes if c['name'] == '读书笔记.txt'), None)
        check('变更清单里能找到刚改过的文件', row is not None, str(staged.changes))
        check('读出了新增行数', bool(row) and row['added'] >= 1, str(row))
        check('合计增删可用',
              staged.total_added >= 1 and staged.total_removed >= 0,
              f'+{staged.total_added} -{staged.total_removed}')

        # ── 取消勾选 → 文件应真的从仓库消失
        group['files'] = [n for n in group['files'] if n != '代码片段.txt']
        result3 = push_and_remember(group, message='移除一个文件', token='x', retries=1,
                                    account={'login': 'freedom0213', 'id': 1},
                                    on_log=lambda *_a: None)
        check('取消勾选后推送成功', result3.ok, result3.detail)
        tree3 = bare_tree(bare)
        check('被取消勾选的文件已从远端消失', '代码片段.txt' not in tree3)
        check('取消勾选后站点也同步移除', '代码片段.md' not in tree3)
        check('其余笔记仍在', '读书笔记.txt' in tree3)

        # ── 只推子集（设计稿 S-01 的勾选）
        result4 = push_and_remember(
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


def test_pull(bare: Path) -> None:
    """[5] 拉取：远端领先 / 自动合并 / 冲突保护 / 编码保持 / 中转区追平。

    用第二个 bare 仓库当远端，并 clone 出「另一台电脑」来制造真实的远端提交 ——
    比对、合并、落盘全是真 git 操作，不联网。
    """
    print('\n[5] 拉取（Pull）')

    folder = _TMP / '拉取测试'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '未改.txt').write_text('第一行\n第二行\n第三行\n',
                                     encoding='utf-8', newline='\n')
    (folder / '两边不同处.txt').write_text('A1\nA2\nA3\nA4\nA5\n',
                                          encoding='utf-8', newline='\n')
    (folder / '同一处.txt').write_text('B1\nB2\nB3\n',
                                       encoding='utf-8', newline='\n')
    # GBK + CRLF：验证「写回保持原样」这条铁律
    (folder / 'GBK笔记.txt').write_bytes('编码一\r\n编码二\r\n'.encode('gbk'))

    group = config.new_group(folder)
    group['id'] = 'pulltest'
    group['repo'] = 'someone/pull-demo'
    group['branch'] = 'main'
    group['site'] = False
    group['files'] = ['未改.txt', '两边不同处.txt', '同一处.txt', 'GBK笔记.txt']

    def local_remote(path, repo, on_log=None):
        url = bare.as_uri()
        if gitops.remote_url(path) != url:
            gitops.git(path, 'remote', 'remove', 'origin', check=False)
            gitops.git(path, 'remote', 'add', 'origin', url)
        return url

    real_ensure = gitops.ensure_remote
    gitops.ensure_remote = local_remote
    try:
        # ── 末尾换行差异：真机踩到过的假冲突 ──
        # 本地笔记常见「最后一行没敲回车」，远端被 GitHub 网页编辑器补了换行。
        # 严格比较会判成「两边都改了同一处」，让用户面对两个一模一样的选项。
        from core.pipeline import _same_text

        check('末尾换行不同不算内容改动', _same_text('a\nb\n', 'a\nb'))
        check('内容不同仍算改动', not _same_text('a\nb\n', 'a\nc\n'))

        _m, _c = gitops.merge_file('a\nb\n34.（标记）\n', 'a\nb\n34.', 'a\nb\n34.\n')
        check('仅末尾换行不同 → 不报冲突', _c == 0, f'冲突数 {_c}')
        _m2, _c2 = gitops.merge_file('a\nb\nX\n', 'a\nb\n本地\n', 'a\nb\n远端\n')
        check('真改了同一处 → 仍然报冲突', _c2 == 1, f'冲突数 {_c2}')

        # ── 基线：先推一次，让远端 == 本地 == 共同祖先 ──
        base = pipeline.push_group(group, message='基线', token='fake-token',
                                   retries=1)
        check('拉取前置：基线推送成功', base.ok, f'{base.reason} / {base.detail}')

        info1 = pipeline.check_remote(group, token='fake-token')
        check('推送过一次之后不再算「首次对接」',
              info1.get('ok') and info1.get('first_time') is False, str(info1))
        check('推送后与远端一致（0/0）',
              (info1.get('ahead'), info1.get('behind')) == (0, 0), str(info1))

        # ── 首次对接：同一个仓库，换一个从没推过的本地文件夹 ──
        # 真机里踩到的场景：把一个**已经有很多提交**的仓库接到一个新的文件夹上。
        # 此时 behind 是「远端本来有多少提交」，不是「远端多了多少」——
        # 界面靠 first_time 分辨这两者，否则用户会以为自己的笔记被别人改过。
        fresh = _TMP / '首次对接的文件夹'
        fresh.mkdir(parents=True, exist_ok=True)
        (fresh / '本地笔记.txt').write_text('本地本来就有的一行\n',
                                            encoding='utf-8', newline='\n')
        fg = config.new_group(fresh)
        fg.update({'id': 'freshbind', 'repo': group['repo'], 'branch': 'main',
                   'site': False, 'files': ['本地笔记.txt']})
        # check_remote 内部会 prepare_workspace（建库 + 接远端），所以直接调即可
        info_f = pipeline.check_remote(fg, token='fake-token')
        check('首次对接能被识别（工作区还没有任何提交）',
              info_f.get('ok') and info_f.get('first_time') is True, str(info_f))
        check('首次对接时 behind 是远端的提交总数（>0）',
              int(info_f.get('behind') or 0) > 0, str(info_f))
        check('首次对接时不会把本地已有的文件判成「本地没改过」',
              (fresh / '本地笔记.txt').read_text(encoding='utf-8')
              == '本地本来就有的一行\n')

        # ── 提交历史（「提交历史」窗口的左栏）──
        history = pipeline.commit_log(group)
        check('本机能读到提交历史', history['ok'] and bool(history['commits']),
              f"{history.get('message')} / {len(history.get('commits') or [])}")
        top = (history.get('commits') or [{}])[0]
        check('最新一条在最前面', top.get('message') == '基线', str(top))
        check('每条都带 sha / 短 sha / 时间 / 作者 / 信息',
              all(k in top for k in ('sha', 'short', 'when', 'author', 'message')),
              str(top))
        check('提交历史只读本地，不因没网而失败',
              history['rev'] == 'HEAD', str(history.get('rev')))

        patch = pipeline.commit_patch(group, str(top.get('sha') or ''))
        check('能取到某次提交的 diff', '验收笔记A.txt' in patch or '未改.txt' in patch
              or '+' in patch, patch[:120].replace('\n', '|'))
        check('diff 里不含提交信息头（界面自己会显示标题）',
              'Author:' not in patch and 'commit ' not in patch[:20], patch[:80])

        remote_history = pipeline.commit_log(group, remote=True, token='fake-token')
        check('远端档能读到（fetch 之后）',
              remote_history['ok'] and remote_history['rev'] == 'origin/main',
              f"{remote_history.get('message')} / {remote_history.get('rev')}")
        check('远端档也有提交', bool(remote_history['commits']),
              str(len(remote_history.get('commits') or [])))

        # 完全没提交过的分组：不能报错，要如实说「还没有」
        empty_log = pipeline.commit_log({'id': 'nohead', 'repo': group['repo'],
                                         'branch': 'main',
                                         'folder': str(folder)})
        check('还没提交过时返回空列表而不是报错',
              empty_log['ok'] and empty_log['commits'] == [], str(empty_log))

        # ── 补丁整理：去噪音、文件头换成人话，但一行正文都不动 ──
        raw = ('diff --git a/笔记.txt b/笔记.txt\n'
               'index 1111111..2222222 100644\n'
               '--- a/笔记.txt\n'
               '+++ b/笔记.txt\n'
               '@@ -1,2 +1,3 @@\n'
               ' 第一行\n'
               '--- 正文里被删掉的一行（原内容以 -- 开头）\n'
               '+新加的一行\n')
        tidy = pipeline._tidy_patch(raw)
        check('整理后不再有 diff --git 行', 'diff --git' not in tidy, tidy[:80])
        check('整理后不再有 index 行', 'index 1111111' not in tidy, tidy[:140])
        check('文件头换成人话（旧版 / 新版）',
              '--- 旧版 · 笔记.txt' in tidy and '+++ 新版 · 笔记.txt' in tidy,
              tidy[:140])
        check('正文里以 --- 开头的行必须原样保留（否则会吃掉笔记内容）',
              '--- 正文里被删掉的一行' in tidy, tidy.replace('\n', '|'))
        # 最要紧的一条：@@ 之后是正文，必须**逐字不变**
        check('@@ 之后的正文逐字不变',
              raw.split('@@', 1)[1] == tidy.split('@@', 1)[1],
              tidy.split('@@', 1)[1].replace('\n', '|'))
        check('文件头还在（界面靠它数文件数）',
              sum(1 for l in tidy.splitlines() if l.startswith('+++ ')) == 1,
              str(tidy.splitlines()))
        newby = pipeline._tidy_patch('diff --git a/新.txt b/新.txt\n'
                                     'new file mode 100644\n--- /dev/null\n'
                                     '+++ b/新.txt\n@@ -0,0 +1 @@\n+内容\n')
        check('新增文件的头写成「（新增文件）」', '（新增文件）' in newby, newby)

        # ── 「另一台电脑」在远端做改动 ──
        other = _TMP / '另一台电脑'
        gitops.git(_TMP, 'clone', bare.as_uri(), str(other))
        gitops.git(other, 'config', 'user.name', 'other')
        gitops.git(other, 'config', 'user.email', 'other@example.com')
        (other / '未改.txt').write_text('第一行\n第二行\n第三行\n远端新加的一行\n',
                                        encoding='utf-8', newline='\n')
        (other / '两边不同处.txt').write_text('A1-远端改\nA2\nA3\nA4\nA5\n',
                                             encoding='utf-8', newline='\n')
        (other / '同一处.txt').write_text('B1\nB2-远端改\nB3\n',
                                          encoding='utf-8', newline='\n')
        (other / 'GBK笔记.txt').write_text('编码一\n编码二\n远端追加\n',
                                           encoding='utf-8', newline='\n')
        gitops.add_all(other)
        gitops.commit(other, '另一台电脑的改动')
        gitops.git(other, 'push', 'origin', 'main')

        # ── 本地改动：一处与远端错开、一处正撞上 ──
        (folder / '两边不同处.txt').write_text('A1\nA2\nA3\nA4\nA5-本地改\n',
                                              encoding='utf-8', newline='\n')
        (folder / '同一处.txt').write_text('B1\nB2-本地改\nB3\n',
                                           encoding='utf-8', newline='\n')

        # ── 计划（只算不写）──
        plan = pipeline.plan_pull(group, token='fake-token')
        check('分析成功', plan.ok, f'{plan.reason} / {plan.detail}')
        check('识别出落后远端', plan.behind >= 1, f'behind={plan.behind}')
        check('本地未改的 → 直接更新',
              {f.name for f in plan.updated} == {'未改.txt', 'GBK笔记.txt'},
              str([(f.name, f.action) for f in plan.files]))
        check('两边错开改的 → 自动合并',
              {f.name for f in plan.merged} == {'两边不同处.txt'},
              str([(f.name, f.action) for f in plan.files]))
        check('同一处相撞 → 冲突',
              {f.name for f in plan.conflicts} == {'同一处.txt'},
              str([(f.name, f.action) for f in plan.files]))
        check('计划阶段没有动任何文件',
              'A5-本地改' in (folder / '两边不同处.txt').read_text(encoding='utf-8')
              and 'B2-本地改' in (folder / '同一处.txt').read_text(encoding='utf-8'))

        # ── 执行 ──
        result = pipeline.apply_pull(group, plan)
        check('执行成功', result.ok, f'{result.reason} / {result.message}')
        # written 含「直接覆盖」和「自动合并」两类 —— 两者都要落盘
        check('写回了三篇（2 篇覆盖 + 1 篇合并结果）',
              set(result.written) == {'未改.txt', 'GBK笔记.txt', '两边不同处.txt'},
              str(sorted(result.written)))
        check('合并结果也记在 merged 里', result.merged == ['两边不同处.txt'],
              str(result.merged))

        text_untouched = (folder / '未改.txt').read_text(encoding='utf-8')
        check('本地未改的拿到了远端内容', '远端新加的一行' in text_untouched,
              text_untouched.replace('\n', '|'))

        merged_text = (folder / '两边不同处.txt').read_text(encoding='utf-8')
        check('自动合并保留了远端的改动', 'A1-远端改' in merged_text,
              merged_text.replace('\n', '|'))
        check('自动合并也保留了本地的改动', 'A5-本地改' in merged_text,
              merged_text.replace('\n', '|'))

        conflict_text = (folder / '同一处.txt').read_text(encoding='utf-8')
        check('冲突的那篇保持本地版本不动', 'B2-本地改' in conflict_text,
              conflict_text.replace('\n', '|'))
        check('冲突没有写进远端版本', 'B2-远端改' not in conflict_text)
        check('结果里列出了冲突篇目', result.conflicts == ['同一处.txt'],
              str(result.conflicts))

        # ── 编码与换行必须原样保留 ──
        raw = (folder / 'GBK笔记.txt').read_bytes()
        check('写回后仍是 GBK 编码（不是 UTF-8）',
              raw.decode('gbk').find('远端追加') >= 0, str(raw[:40]))
        check('写回后仍是 CRLF 换行', b'\r\n' in raw, str(raw[:60]))

        # ── 备份 ──
        check('写回前做了备份', result.backup_dir is not None
              and result.backup_dir.is_dir(), str(result.backup_dir))
        if result.backup_dir:
            backed = result.backup_dir / '未改.txt'
            check('备份里存的是被覆盖前的内容',
                  backed.is_file()
                  and '远端新加的一行' not in backed.read_text(encoding='utf-8'),
                  str(result.backup_dir))

        # ── 中转区追平远端：下一次推送必须是快进 ──
        ws = pipeline.workspace_dir(group)
        ahead, behind = gitops.ahead_behind(ws, 'main')
        check('中转区已与远端对齐', (ahead, behind) == (0, 0), f'{ahead}/{behind}')

        (folder / '未改.txt').write_text(text_untouched + '再补一行\n',
                                        encoding='utf-8', newline='\n')
        after = pipeline.push_group(group, message='拉取后的推送', token='fake-token',
                                    retries=1)
        check('拉取之后的推送能成功（不存在非快进拒绝）', after.ok,
              f'{after.reason} / {after.detail}')

        # ── 本地领先：中转区有未推送的提交（例如上次推送失败的残留）──
        (folder / '同一处.txt').write_text('B1\nB2-本地改\nB3\n本地又改一行\n',
                                           encoding='utf-8', newline='\n')
        pipeline.stage_group(group, account={'login': 'tester', 'id': 1})
        gitops.commit(pipeline.workspace_dir(group), '本地提交但没推出去')
        plan2 = pipeline.plan_pull(group, token='fake-token')
        check('远端无更新时提示「本地有未推送的改动」',
              plan2.ok and plan2.reason == pipeline.REASON_LOCAL_AHEAD,
              f'{plan2.reason} / {plan2.message}')
        check('这种情况下不写任何文件', not plan2.writes)

        # ── 远端只改了自动生成的文件 ──
        # 真机反馈出来的场景：用户在 GitHub 网页上编辑了 <笔记>.md（生成物），
        # 本地笔记原文并没有变。这时绝不能说「已经是最新」——用户会觉得软件在骗他。
        # 先让「另一台电脑」跟上远端（中途主仓库推过一次，它落后了）
        gitops.git(other, 'fetch', 'origin', 'main')
        gitops.git(other, 'reset', '--hard', 'origin/main')
        (other / 'Java八股.md').write_text('# 网页上改的\n',
                                           encoding='utf-8', newline='\n')
        gitops.add_all(other)
        gitops.commit(other, '网页上改了生成文件')
        gitops.git(other, 'push', 'origin', 'main')

        plan3 = pipeline.plan_pull(group, token='fake-token')
        check('远端只改生成物时给出专门的原因',
              plan3.ok and plan3.reason == pipeline.REASON_ARTIFACTS_ONLY,
              f'{plan3.reason} / {plan3.message}')
        check('列出那些不同步的路径', plan3.outside == ['Java八股.md'],
              str(plan3.outside))
        check('这种情形下本地笔记一律不动', not plan3.writes)

        res3 = pipeline.apply_pull(group, plan3)
        aligned = gitops.ahead_behind(pipeline.workspace_dir(group), 'main')
        check('生成物场景下也对齐中转区（否则推送会被「远端领先」拦住）',
              aligned == (0, 0), str(aligned))
        check('并且没有改写任何本地笔记', not res3.written and not res3.failed,
              f'{res3.written} / {res3.failed}')

        # ── 远端改的是「仓库里其他人的文件」，不是生成物 ──
        # 🔴 这两类的后果**相反**：生成物会被下次推送覆盖，外来文件一个都不碰。
        # 混在一句「自动生成的文件」里说，就是在撒谎（P0 改完之后尤其明显）。
        (other / 'LICENSE').write_text('另一个人的 LICENSE\n', encoding='utf-8')
        (other / 'tools').mkdir(exist_ok=True)
        (other / 'tools' / 'sync.py').write_text('print(1)\n', encoding='utf-8')
        gitops.add_all(other)
        gitops.commit(other, '加了仓库里本来就有的文件')
        gitops.git(other, 'push', 'origin', 'main')

        plan4 = pipeline.plan_pull(group, token='fake-token')
        check('远端改外来文件时也走「不用写回」这条路',
              plan4.ok and plan4.reason == pipeline.REASON_ARTIFACTS_ONLY,
              f'{plan4.reason} / {plan4.message}')
        check('外来文件被分到 foreign（而不是当成生成物）',
              set(plan4.foreign) == {'LICENSE', 'tools/sync.py'},
              f'foreign={plan4.foreign} generated={plan4.generated}')
        check('生成物里不该混进外来文件',
              not ({'LICENSE', 'tools/sync.py'} & set(plan4.generated)),
              str(plan4.generated))
        check('这种情形下本地笔记同样一律不动', not plan4.writes)
        pipeline.apply_pull(group, plan4)

        # ── 判据本身（纯函数，快）──
        g = {'docs_dir': '', 'files': ['Java八股.txt', '读书笔记.txt'],
             'pushed_paths': ['Java八股.txt', 'Java八股.md', 'index.html']}
        check('站点固定产物算我们的',
              all(pipeline.is_our_artifact(g, p) for p in
                  ('index.html', '_sidebar.md', '.nojekyll', 'README.md')))
        check('assets/ 下的资源算我们的',
              pipeline.is_our_artifact(g, 'assets/docsify.min.js'))
        check('笔记对应的页面算我们的',
              pipeline.is_our_artifact(g, 'Java八股.md')
              and pipeline.is_our_artifact(g, '读书笔记.md'))
        check('pushed_paths 里有记录的一律算我们的',
              pipeline.is_our_artifact(g, 'Java八股.txt'))
        check('LICENSE / tools/ / 别人的 md / requirements.txt 都不算我们的',
              not any(pipeline.is_our_artifact(g, p) for p in
                      ('LICENSE', 'tools/sync.py', '别人的说明.md',
                       'requirements.txt', '笔记备份.txt')))
        check('没有记录时的兜底也是保守的（名字对不上就算别人的）',
              not pipeline.is_our_artifact({'docs_dir': '', 'files': []}, 'LICENSE')
              and pipeline.is_our_artifact({'docs_dir': '', 'files': []}, 'index.html'))
    finally:
        gitops.ensure_remote = real_ensure



# ───────── 6. 仓库里本来就有的文件不许被删（真机反馈的 P0）─────────

def test_foreign_files(tmp: Path, bare: Path) -> None:
    """绑到一个**已经有内容**的仓库时，仓库里的其他文件必须原封不动。

    推送的机制是「清空工作区 → 按白名单重建」，于是「上次提交里有、这次没重建
    出来」的路径在本次提交里就是一条删除。以前这些删除会落进兜底桶、被显示成
    「自动生成的文档站 N 个文件」—— 用户的 LICENSE / tools/ / 手写 .md 被删掉时，
    界面上看起来像文档站在更新（真机反馈查出来的误导）。

    现在的规则：只有**本工具产出过**的文件（配置里的 ``pushed_paths``）才允许被
    删除；仓库里其他东西一律移出本次提交、保住不动。没有那份记录时保守处理：
    一次删除都不发生。
    """
    print('\n[6] 仓库里本来就有的文件不许被删')

    folder = tmp / '外来文件测试'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '我的笔记.txt').write_text('第一行\n', encoding='utf-8')

    group = config.new_group(folder)
    group['id'] = 'foreign'
    group['repo'] = 'someone/has-content'
    group['files'] = ['我的笔记.txt']

    def local_remote(path, repo, on_log=None):
        url = bare.as_uri()
        if gitops.remote_url(path) != url:
            gitops.git(path, 'remote', 'remove', 'origin', check=False)
            gitops.git(path, 'remote', 'add', 'origin', url)
        return url

    real_ensure = gitops.ensure_remote
    gitops.ensure_remote = local_remote
    account = {'login': 'freedom0213', 'id': 1}
    quiet = lambda *_a: None                                     # noqa: E731
    try:
        # ── 先把远端造成「一个有内容的仓库」：里面有别的东西，不是空仓库 ──
        seed = tmp / 'seed'
        subprocess.run(['git', 'clone', '-q', bare.as_uri(), str(seed)],
                       check=True, capture_output=True)
        (seed / 'LICENSE').write_text('MIT License\n', encoding='utf-8')
        (seed / 'README.md').write_text('# 我手写的说明\n', encoding='utf-8')
        (seed / 'requirements.txt').write_text('requests\n', encoding='utf-8')
        (seed / 'tools').mkdir()
        (seed / 'tools' / 'sync.py').write_text('print(1)\n', encoding='utf-8')
        gitops.git(seed, 'add', '-A')
        gitops.git(seed, '-c', 'user.name=seed', '-c', 'user.email=seed@x',
                   'commit', '-q', '-m', 'seed')
        gitops.git(seed, 'push', '-q', 'origin', 'HEAD:main')
        check('造好了「已有内容的仓库」',
              {'LICENSE', 'requirements.txt', 'tools/sync.py'} <= set(bare_tree(bare)))

        # 真实流程在这里会先引导用户 Pull 一次（远端领先 → 不允许非快进推送），
        # 那一步会把工作区对齐到远端。**正因为对齐了，工作区才看得见远端那些文件**，
        # 于是"这次提交会删掉什么"才有得算 —— 这正是风险真正发生的位置。
        ws = pipeline.workspace_dir(group)
        pipeline.prepare_workspace(group, on_log=quiet)
        gitops.fetch(ws, 'main')
        gitops.reset_hard(ws, 'origin/main')
        check('工作区已对齐远端（模拟先 Pull 过一次）',
              set(gitops.list_tree(ws)) == set(bare_tree(bare)), str(gitops.list_tree(ws)))

        # ── 首次推送：我们的笔记进去，别人的东西一样都不许少 ──
        staged = pipeline.stage_group(group, on_log=quiet)
        check('stage_group 成功', staged.ok, staged.detail)
        check('外来文件被判为「不归本工具管」',
              set(staged.untouched) == {'LICENSE', 'requirements.txt', 'tools/sync.py'},
              str(staged.untouched))
        check('没有归属记录时一个删除都不许发生',
              staged.removed == [], str(staged.removed))
        check('外来文件不再混进「站点产物」那一组（以前删除就藏在那里）',
              not ({'LICENSE', 'requirements.txt', 'tools/sync.py'}
                   & set(staged.artifact_paths)), str(staged.artifact_paths))
        check('会被重新生成的同名文件不算「外来」', 'README.md' not in staged.untouched)
        check('这次要推的东西是有的', staged.has_changes)

        result = push_and_remember(group, message='首次推送', token='x', retries=1,
                                   account=account, on_log=quiet)
        check('推送成功', result.ok, f'{result.reason} / {result.detail}')
        after = set(bare_tree(bare))
        missing = {'LICENSE', 'requirements.txt', 'tools/sync.py'} - after
        check('仓库里本来就有的文件全都在（这次修复的核心）',
              not missing, f'被删掉的是：{sorted(missing)}')
        check('我们的笔记推上去了', '我的笔记.txt' in after)
        check('记下了「本工具产出的路径」',
              '我的笔记.txt' in (group.get('pushed_paths') or []),
              str(group.get('pushed_paths'))[:120])

        # ── 再推一次（内容有改动），外来文件仍然不许动 ──
        (folder / '我的笔记.txt').write_text('第一行\n第二行\n', encoding='utf-8')
        result2 = push_and_remember(group, message='第二次推送', token='x', retries=1,
                                    account=account, on_log=quiet)
        check('第二次推送成功', result2.ok, f'{result2.reason} / {result2.detail}')
        after2 = set(bare_tree(bare))
        check('第二次推送后外来文件仍然都在',
              not ({'LICENSE', 'requirements.txt', 'tools/sync.py'} - after2),
              str(sorted(after2)))

        # ── 有了归属记录之后：取消勾选自己的笔记，它仍应真的从仓库消失 ──
        (folder / '第二篇.txt').write_text('第二篇\n', encoding='utf-8')
        g3 = dict(group)
        g3['files'] = ['我的笔记.txt', '第二篇.txt']
        r3 = push_and_remember(g3, message='加一篇', token='x', retries=1,
                               account=account, on_log=quiet)
        check('加一篇笔记推送成功', r3.ok, r3.detail)
        check('第二篇的页面也在', '第二篇.md' in bare_tree(bare))

        g4 = dict(g3)
        g4['files'] = ['我的笔记.txt']          # ← 取消勾选第二篇
        s4 = pipeline.stage_group(g4, on_log=quiet)
        check('取消勾选的那篇被判为「我们自己的删除」',
              set(s4.removed) == {'第二篇.txt', '第二篇.md'}, str(s4.removed))
        # 外来文件每次推送都会被"保住"一次（它们的删除请求每轮都会被拦下），
        # 所以理应出现在 untouched 里；关键是它们绝不出现在 removed 里。
        check('外来文件只是「保住」，没有进删除名单',
              set(s4.untouched) == {'LICENSE', 'requirements.txt', 'tools/sync.py'}
              and not (set(s4.untouched) & set(s4.removed)), str(s4.untouched))
        r4 = push_and_remember(g4, message='去掉第二篇', token='x', retries=1,
                               account=account, on_log=quiet)
        check('去掉第二篇的推送成功', r4.ok, r4.detail)
        tree4 = set(bare_tree(bare))
        check('取消勾选后它确实从仓库消失（设计意图仍然成立）',
              '第二篇.txt' not in tree4 and '第二篇.md' not in tree4,
              str(sorted(tree4)))
        check('顺手再看一眼：外来文件还在',
              not ({'LICENSE', 'requirements.txt', 'tools/sync.py'} - tree4))

        # ── 自动推送那条路（不带 keep）也必须挡住外来删除 ──
        # keep=None 表示"提交全部改动"，是最容易漏掉的一处
        g5 = dict(g4)
        g5['pushed_paths'] = list(g4.get('pushed_paths') or [])
        (folder / '我的笔记.txt').write_text('第一行\n第二行\n第三行\n', encoding='utf-8')
        st5 = pipeline.stage_group(g5, on_log=quiet)
        res5 = pipeline.finalize_push(g5, st5, message='一键直推', token='x',
                                      keep=None, retries=1, on_log=quiet)
        check('不带 keep 的一键直推也成功', res5.ok, res5.detail)
        tree5 = set(bare_tree(bare))
        check('一键直推同样不会碰外来文件',
              not ({'LICENSE', 'requirements.txt', 'tools/sync.py'} - tree5),
              str(sorted(tree5)))
    finally:
        gitops.ensure_remote = real_ensure

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

    bare_pull = _TMP / 'remote_pull.git'
    bare_pull.mkdir(parents=True, exist_ok=True)
    init_pull = gitops.git(bare_pull, 'init', '--bare', '-b', 'main', check=False)
    assert init_pull.returncode == 0, init_pull
    test_pull(bare_pull)

    # 绑一个「本来就有内容」的仓库：外来文件不许被删
    bare_foreign = _TMP / 'remote_foreign.git'
    bare_foreign.mkdir(parents=True, exist_ok=True)
    init_foreign = gitops.git(bare_foreign, 'init', '--bare', '-b', 'main', check=False)
    assert init_foreign.returncode == 0, init_foreign
    test_foreign_files(_TMP, bare_foreign)

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
