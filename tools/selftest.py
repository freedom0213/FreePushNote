# -*- coding: utf-8 -*-
"""自测脚本：不启动 GUI，直接验证 core 的底层模块。

用法（在 pushnote 目录下）::

    .venv\\Scripts\\python.exe tools\\selftest.py

三个套件分工（改完代码全跑一遍）::

    tools/selftest.py           envprobe / gitops / config 冒烟
    tools/auth_selftest.py      GitHub 认证（注入假传输，不联网）
    tools/pipeline_selftest.py  推送链路（本地 bare 仓库当远端，不联网）

config / convert / site / pipeline 的完整覆盖在 pipeline_selftest.py 里 ——
那些用例需要真仓库、真文件才能验，放在这里会既慢又重复。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Windows 控制台默认 GBK，统一成 UTF-8 以免中文乱码
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        try:
            _s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config, envprobe, gitops  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, ok: bool, extra: str = '') -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f'  [ok]   {name}')
    else:
        _failed += 1
        print(f'  [FAIL] {name}   {extra}')


def test_config() -> None:
    """基础冒烟：结构、往返、原子写。完整校验见 pipeline_selftest。"""
    print('== config ==')

    cfg = config.blank_config()
    check('blank_config 是 v2 结构',
          set(cfg) == {'version', 'defaults', 'groups'} and cfg['version'] == 2)
    check('站点默认放仓库根（docs_dir 为空）', config.DEFAULTS['docs_dir'] == '')

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cfg_path = td / 'nested' / 'config.json'
        check('load 不存在的路径返回空白配置',
              config.load(cfg_path)['groups'] == [])

        folder = td / '中文笔记'
        folder.mkdir()
        (folder / 'a.txt').write_text('x', encoding='utf-8')

        group = config.new_group(folder)
        group['id'] = 'demo'
        group['repo'] = 'someone/demo-notes'
        group['files'] = ['a.txt']
        config.upsert_group(cfg, group)
        config.save(cfg, cfg_path)

        again = config.load(cfg_path)
        check('save/load 往返一致', again['groups'][0]['folder'] == str(folder))
        check('落盘为 UTF-8 且中文正常',
              '中文笔记' in cfg_path.read_text(encoding='utf-8'))
        check('save 自动创建父目录', cfg_path.exists())
        check('无残留 .tmp 文件', not list(cfg_path.parent.glob('*.tmp')))
        check('group_by_id 查得到', config.group_by_id(again, 'demo') is not None)
        check('工作区落在 workspaces/<id> 下',
              config.workspace_dir(group).name == 'demo'
              and config.workspace_dir(group).parent == config.WORKSPACES_DIR)

        bad = td / 'bad.json'
        bad.write_text('{ not json', encoding='utf-8')
        try:
            config.load(bad)
            check('坏 JSON 抛 ConfigError', False, '未抛异常')
        except config.ConfigError:
            check('坏 JSON 抛 ConfigError', True)


def test_envprobe() -> None:
    print('== envprobe ==')
    proxy = envprobe.git_http_proxy()
    print(f'  git http.proxy = {proxy!r}')
    check('能读到 git http.proxy（非空）', bool(proxy), proxy)

    fake = {'http_proxy': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1',
            'NO_PROXY': 'localhost', 'PATH': 'x'}
    env = envprobe.clean_env(base=fake, proxy='http://127.0.0.1:7890')
    proxy_keys = sorted(k.upper() for k in env if k.lower().endswith('proxy'))
    check('代理键只剩干净的两个（旧值全被清掉）',
          set(proxy_keys) == {'HTTP_PROXY', 'HTTPS_PROXY'}, str(proxy_keys))
    check('旧 NO_PROXY 已清除',
          'NO_PROXY' not in {k.upper() for k in env})
    check('保留其它变量', env.get('PATH') == 'x')
    check('显式注入代理', env.get('HTTP_PROXY') == 'http://127.0.0.1:7890')

    env2 = envprobe.clean_env(base=fake, proxy='')
    check('proxy 传空串时不注入', 'HTTP_PROXY' not in env2)


def test_gitops() -> None:
    print('== gitops ==')

    # --- 写操作：临时仓库（绝不推送）---
    # 只读探测也在这个临时仓库上做，**不依赖本机任何真实仓库的位置** ——
    # 之前写死了某一个目录，项目一搬家这些检查就静默跳过了。
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        td = Path(td)
        repo = td / 'repo'
        gitops.init_repo(repo, branch='main')
        check('init_repo 后 is_repo 为真', gitops.is_repo(repo))
        check('空仓库 head_exists 为假', not gitops.head_exists(repo))
        check('.gitattributes 已生成', (repo / '.gitattributes').exists())
        check('已关闭 core.quotepath（中文路径不被转义成八进制）',
              gitops.stdout_of(gitops.git(repo, 'config', 'core.quotepath')) == 'false')

        (repo / 'a.txt').write_text('hello\n', encoding='utf-8', newline='\n')
        check('新增文件后 has_changes 为真', gitops.has_changes(repo))

        gitops.add_all(repo)
        staged_names = sorted(c['name'] for c in gitops.staged_numstat(repo))
        # .gitattributes 是 init_repo 自己写的（统一 LF），会一起进第一次提交 ——
        # 这是有意的：仓库里 eol=lf 才不会出现「本地没改却显示整个文件都改了」
        check('暂存后能让 staged_numstat 读出文件',
              staged_names == ['.gitattributes', 'a.txt'], str(staged_names))
        check('暂存后 has_staged_changes 为真', gitops.has_staged_changes(repo))

        gitops.commit(repo, 'chore: test')
        check('提交后 has_changes 为假', not gitops.has_changes(repo))
        check('提交后 has_staged_changes 为假', not gitops.has_staged_changes(repo))
        check('提交后 head_exists 为真', gitops.head_exists(repo))
        check('short_hash 可用', len(gitops.short_hash(repo)) >= 7)
        check('current_branch 为 main', gitops.current_branch(repo) == 'main',
              gitops.current_branch(repo))

        # 最近提交：侧栏「最近推送」读的就是它
        commits = gitops.recent_commits(repo, 3)
        check('recent_commits 读到一条', len(commits) == 1, str(commits))
        check('recent_commits 的字段齐全',
              bool(commits) and set(commits[0]) == {'hash', 'message', 'ts'},
              str(commits))
        check('recent_commits 的消息正确',
              bool(commits) and commits[0]['message'] == 'chore: test',
              str(commits))

        # 中文路径不能因为编码问题读错（core.quotepath 的作用）
        (repo / '中文笔记.txt').write_text('内容\n', encoding='utf-8')
        gitops.add_all(repo)
        names = [c['name'] for c in gitops.staged_numstat(repo)]
        check('中文文件名不被转义', names == ['中文笔记.txt'], str(names))

        url = gitops.ensure_remote(repo, 'someone/demo-notes')
        check('ensure_remote 正确写入 origin',
              url == 'https://github.com/someone/demo-notes.git'
              and gitops.remote_url(repo) == url)

        bare = td / 'bare'
        gitops.init_repo(bare, branch='main')
        ok, tries = gitops.push(bare, on_log=lambda *_a: None)
        check('无远程时 push 返回 (False, 0) 而非抛异常',
              ok is False and tries == 0, f'{ok} {tries}')

    # --- 认证相关的小工具（真实验证在 auth_selftest / pipeline_selftest）---
    check('token_helper 从环境变量读令牌',
          gitops.TOKEN_ENV_VAR in gitops.token_helper())
    check('令牌不进命令行参数',
          all('SECRET' not in a for a in gitops.credential_args('SECRET')))
    name, email = gitops.identity_for_account('someone', 7)
    check('提交身份用 noreply 邮箱',
          name == 'someone' and email == '7+someone@users.noreply.github.com')


def test_ssh_rewrite_defense() -> None:
    """系统级 gitconfig 把 GitHub 地址改写成 SSH 时，推送必须仍走 https。

    这不是假想：本机 ``D:\\skywaimai\\Git\\etc\\gitconfig`` 里真有
    ``[url "git@github.com:"] insteadOf = https://github.com/``，
    于是「双击同步笔记」那个脚本的 ``git push`` 全被改成 SSH 直连，
    而那条连接在本机是被重置的 —— 连试 3 次全失败，且报错完全不提配置。
    """
    print('== gitops：url.insteadOf 改写防护 ==')

    check('识别 ssh:// 形式', gitops.looks_like_ssh('ssh://git@github.com/a/b.git'))
    check('识别 scp 形式', gitops.looks_like_ssh('git@github.com:owner/repo.git'))
    check('https 不算 SSH', not gitops.looks_like_ssh('https://github.com/a/b.git'))
    check('本机路径不算 SSH（自测拿裸仓库当远端，别误拦）',
          not gitops.looks_like_ssh('C:/tmp/x/bare')
          and not gitops.looks_like_ssh('/tmp/x/bare'))

    env = gitops.push_env('SECRET')
    check('推送子进程无视系统级 gitconfig',
          env.get('GIT_CONFIG_NOSYSTEM') == '1')
    # 继承来的小写 *_proxy 必须清掉（它们可能指向不支持 CONNECT 的代理，
    # 会让 git 静默挂死、零输出）；git 自己配置里的 http.proxy 再以大写注入。
    # 注意别用 k.lower() 去比 —— 那会把注入的大写 HTTP_PROXY 也一起算进去。
    check('清掉了继承来的小写 *_proxy',
          'http_proxy' not in env and 'https_proxy' not in env)
    check('git 的 http.proxy 仍以大写形式注入给子进程',
          env.get('HTTP_PROXY') == env.get('HTTPS_PROXY')
          == (envprobe.git_http_proxy() or None))
    check('令牌随环境传入', env.get(gitops.TOKEN_ENV_VAR) == 'SECRET')

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        td = Path(td)
        repo = td / 'repo'
        gitops.init_repo(repo, branch='main')
        gitops.ensure_remote(repo, 'example/demo')

        # 用 GIT_CONFIG_SYSTEM 指向一份「带改写规则的假系统配置」，
        # 这样能在不碰本机任何真实配置的前提下复现同一个坑。
        sabotage = td / 'sabotage.gitconfig'
        sabotage.write_text('[url "git@github.com:"]\n'
                            '\tinsteadOf = https://github.com/\n',
                            encoding='utf-8', newline='\n')

        old = os.environ.get('GIT_CONFIG_SYSTEM')
        os.environ['GIT_CONFIG_SYSTEM'] = str(sabotage)
        try:
            polluted = gitops.resolved_remote_url(repo, env=envprobe.clean_env())
            check('被污染时地址确实变成 SSH（说明这个用例是有效的）',
                  polluted == 'git@github.com:example/demo.git', polluted)
            safe = gitops.resolved_remote_url(repo, env=gitops.push_env())
            check('换成 push_env 后地址回到 https',
                  safe == 'https://github.com/example/demo.git', safe)

            # 万一将来有人把改写规则写进**用户级**配置（NOSYSTEM 管不到那儿），
            # push 必须当场拒绝，而不是悄悄改用本机 SSH 密钥认证 ——
            # 那会「成功推送但署了另一个身份」，比失败更难发现。
            real = gitops.resolved_remote_url
            gitops.resolved_remote_url = (
                lambda *a, **k: 'git@github.com:example/demo.git')
            try:
                logs: list[str] = []
                ok, tries = gitops.push(repo, token='SECRET', on_log=logs.append)
                check('地址是 SSH 形式时 push 直接拒绝',
                      ok is False and tries == 0, f'{ok} {tries}')
                check('并说明了原因（提到 insteadOf）',
                      any('insteadOf' in line for line in logs),
                      ' | '.join(logs))
            finally:
                gitops.resolved_remote_url = real
        finally:
            if old is None:
                os.environ.pop('GIT_CONFIG_SYSTEM', None)
            else:
                os.environ['GIT_CONFIG_SYSTEM'] = old


def main() -> int:
    test_config()
    test_envprobe()
    test_gitops()
    test_ssh_rewrite_defense()
    print()
    print(f'通过 {_passed} 项，失败 {_failed} 项')
    return 1 if _failed else 0


if __name__ == '__main__':
    sys.exit(main())
