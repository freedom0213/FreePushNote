# -*- coding: utf-8 -*-
"""自测脚本：不启动 GUI，直接验证 core 各模块。

用法（在 pushnote 目录下）:
    py tools/selftest.py

遵循「先客观自测，再交付」的原则：任何改动后先跑这里。
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
    print('== config ==')

    cfg = config.blank_config()
    check('blank_config 结构正确',
          set(cfg) == {'version', 'defaults', 'bindings', 'active_id'})

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cfg_path = td / 'nested' / 'config.json'

        check('load 不存在的路径返回空白配置',
              config.load(cfg_path)['bindings'] == [])

        note = td / 'a.txt'
        note.write_text('hello', encoding='utf-8')
        binding = {'id': 'demo', 'name': '演示', 'note_path': str(note),
                   'repo': 'someone/demo-notes', 'mode': 'auto'}

        cfg = config.blank_config()
        config.upsert_binding(cfg, binding)
        config.save(cfg, cfg_path)

        again = config.load(cfg_path)
        check('save/load 往返一致', again['bindings'][0]['note_path'] == str(note))
        check('落盘为 UTF-8 且中文正常',
              '演示' in cfg_path.read_text(encoding='utf-8'))
        check('save 自动创建父目录', cfg_path.exists())
        check('active_id 自动填充', again['active_id'] == 'demo')
        check('无残留 .tmp 文件', not list(cfg_path.parent.glob('*.tmp')))

        check('合法绑定无错误', config.validate_binding(binding) == [])
        check('相对路径被拒',
              any('绝对路径' in e for e in
                  config.validate_binding({**binding, 'note_path': 'a.txt'})))
        check('非 .txt 被拒',
              any('.txt' in e for e in
                  config.validate_binding({**binding, 'note_path': str(td / 'x.md')})))
        check('不存在的文件被拒',
              any('不存在' in e for e in
                  config.validate_binding({**binding, 'note_path': str(td / 'no.txt')})))
        check('repo 格式被校验',
              any('owner/name' in e for e in
                  config.validate_binding({**binding, 'repo': 'nope'})))
        check('mode 被校验',
              any('mode' in e for e in
                  config.validate_binding({**binding, 'mode': 'xxx'})))
        check('id 非法被拒',
              any('id' in e for e in
                  config.validate_binding({**binding, 'id': 'Bad_ID'})))

        bad = td / 'bad.json'
        bad.write_text('{ not json', encoding='utf-8')
        try:
            config.load(bad)
            check('坏 JSON 抛 ConfigError', False, '未抛异常')
        except config.ConfigError:
            check('坏 JSON 抛 ConfigError', True)

    check('workdir 显式填写优先',
          config.workdir_for({'id': 'x', 'workdir': 'C:/tmp'}) == Path('C:/tmp'))
    check('workdir 默认派生到 repos/<id>',
          config.workdir_for({'id': 'abc'}).name == 'abc')

    cfg = config.blank_config()
    with tempfile.TemporaryDirectory() as td:
        note = Path(td) / 'a.txt'
        note.write_text('x', encoding='utf-8')
        base = {'name': 'n', 'note_path': str(note), 'repo': 'a/b', 'mode': 'auto'}
        config.upsert_binding(cfg, {**base, 'id': 'one'})
        config.upsert_binding(cfg, {**base, 'id': 'two'})
        check('upsert 新增两条', len(cfg['bindings']) == 2)
        config.upsert_binding(cfg, {**base, 'id': 'one', 'name': '改名'})
        got = config.get_binding(cfg, 'one')
        check('upsert 覆盖而非新增',
              len(cfg['bindings']) == 2 and got is not None and got['name'] == '改名')
        cfg['active_id'] = 'one'
        config.remove_binding(cfg, 'one')
        check('remove 后 active 自动转移', cfg['active_id'] == 'two')


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

    # --- 只读探测：现成的 java-notes 仓库 ---
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
        check('java-notes 目录存在', False, str(java_notes))

    # --- 写操作：临时仓库（绝不推送）---
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        td = Path(td)
        repo = td / 'repo'
        gitops.init_repo(repo, branch='main')
        check('init_repo 后 is_repo 为真', gitops.is_repo(repo))
        check('空仓库 head_exists 为假', not gitops.head_exists(repo))
        check('.gitattributes 已生成', (repo / '.gitattributes').exists())

        (repo / 'a.txt').write_text('hello\n', encoding='utf-8', newline='\n')
        check('新增文件后 has_changes 为真', gitops.has_changes(repo))

        gitops.add_all(repo)
        gitops.commit(repo, 'chore: test')
        check('提交后 has_changes 为假', not gitops.has_changes(repo))
        check('提交后 head_exists 为真', gitops.head_exists(repo))

        url = gitops.ensure_remote(repo, 'someone/demo-notes')
        check('ensure_remote 正确写入 origin',
              url == 'https://github.com/someone/demo-notes.git'
              and gitops.remote_url(repo) == url)

        bare = td / 'bare'
        gitops.init_repo(bare, branch='main')
        ok, tries = gitops.push(bare, on_log=lambda *_a: None)
        check('无远程时 push 返回 (False, 0) 而非抛异常',
              ok is False and tries == 0, f'{ok} {tries}')


def main() -> int:
    test_config()
    test_envprobe()
    test_gitops()
    print()
    print(f'通过 {_passed} 项，失败 {_failed} 项')
    return 1 if _failed else 0


if __name__ == '__main__':
    sys.exit(main())
