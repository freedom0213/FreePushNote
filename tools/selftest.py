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

    # --- 只读探测：现成的 java-notes 仓库（不在就跳过，不算失败）---
    java_notes = ROOT.parent / 'java-notes'
    if java_notes.is_dir():
        check('is_repo(java-notes) 为真', gitops.is_repo(java_notes))
        check('head_exists(java-notes) 为真', gitops.head_exists(java_notes))
        branch = gitops.current_branch(java_notes)
        check('current_branch 为 main', branch == 'main', branch)
        url = gitops.remote_url(java_notes)
        check('remote_url 指向 Java-BAGU-notes',
              url.endswith('freedom0213/Java-BAGU-notes.git'), url)
    else:
        print(f'  [skip] 没有找到 {java_notes}，跳过只读探测')

    # --- 写操作：临时仓库（绝不推送）---
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
        gitops.commit(repo, 'chore: test')
        check('提交后 has_changes 为假', not gitops.has_changes(repo))
        check('提交后 head_exists 为真', gitops.head_exists(repo))
        check('short_hash 可用', len(gitops.short_hash(repo)) >= 7)

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


def main() -> int:
    test_config()
    test_envprobe()
    test_gitops()
    print()
    print(f'通过 {_passed} 项，失败 {_failed} 项')
    return 1 if _failed else 0


if __name__ == '__main__':
    sys.exit(main())
