# -*- coding: utf-8 -*-
"""界面接线自测：验证「账号 → 纳管 → 推送 → 状态回填」这条链在界面上真的通。

干跑整个流程，但不点任何模态对话框（模态框会卡住脚本）。能验到：

* Push 按钮在各情形下的文案（未绑账号 / 未纳管 / 可推送 / 已是最新）
* 纳管对话框：文件清单、全选、勾选计数、步骤切换、仓库地址解析、校验报错
* 推送对话框：逐篇笔记的增删行数、取消勾选、``keep`` 列表算得对不对
* 左栏「受管理的文件夹」、状态栏「归属」是否读到真实配置
* 推送后状态回填：``is_pushed`` 变真 → 按钮变「已是最新，无需推送」
* 「只推选中的」真的生效：取消勾选的笔记，仓库里保持旧内容

远端用**本地 bare 仓库**，不联网、不碰任何真实 GitHub 仓库。

用法：
    .venv\\Scripts\\python.exe tools\\app_flow_selftest.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = Path(tempfile.mkdtemp(prefix='pushnote_appflow_'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PUSHNOTE_HOME'] = str(_TMP / 'home')

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from core import config, ghauth, gitops, pipeline  # noqa: E402

from app import account as account_mod  # noqa: E402
from app.main import build_app  # noqa: E402
from app.widgets.managedialog import ManageFolderDialog  # noqa: E402
from app.widgets.pushdialog import PushDialog  # noqa: E402
from app.window import FreePushWindow  # noqa: E402

# 模态框一律不弹：脚本要能无人值守跑完
QMessageBox.exec = lambda self: 0                                  # type: ignore[method-assign]
QMessageBox.information = staticmethod(lambda *a, **k: None)       # type: ignore
QMessageBox.warning = staticmethod(lambda *a, **k: None)           # type: ignore
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)  # type: ignore

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


NOTE_A = """第一篇笔记

第一行要点。
第二行要点。

新的一段。
"""
NOTE_B = """===== 集合 =====

1：ArrayList 和 LinkedList 的区别？

  一个数组，一个链表。
"""
SECRET = '这是不该上传的内容\n'


def prepare() -> tuple[Path, Path]:
    folder = _TMP / '笔记文件夹'
    folder.mkdir(parents=True, exist_ok=True)
    # 刻意用 CRLF 写：Windows 记事本的真实产物，顺带覆盖换行归一化
    (folder / '第一篇.txt').write_text(NOTE_A, encoding='utf-8', newline='\r\n')
    (folder / '第二篇.txt').write_text(NOTE_B, encoding='utf-8')
    (folder / '密码备份.txt').write_text(SECRET, encoding='utf-8')

    bare = _TMP / 'remote.git'
    bare.mkdir(parents=True, exist_ok=True)
    gitops.git(bare, 'init', '--bare', '-b', 'main', check=False)
    return folder, bare


def bare_show(bare: Path, path: str) -> str | None:
    r = gitops.git(bare, '-c', 'core.quotepath=false', 'show', f'HEAD:{path}',
                   check=False)
    return None if r.returncode != 0 else (r.stdout or b'').decode('utf-8', 'replace')


def bare_tree(bare: Path) -> list[str]:
    r = gitops.git(bare, '-c', 'core.quotepath=false', 'ls-tree', '-r',
                   '--name-only', 'HEAD', check=False)
    return [l for l in gitops.stdout_of(r).splitlines() if l.strip()]


def main() -> int:  # noqa: C901
    print('=' * 66)
    print('FreePushNote 界面接线自测（offscreen，不联网）')
    print('=' * 66)

    app = build_app([])
    folder, bare = prepare()

    # ───────────────── 1. 未绑账号 ─────────────────
    print('\n[1] 未绑定账号')
    win = FreePushWindow()
    win.load_path(str(folder / '第一篇.txt'))
    check('Push 按钮 = 绑定 GitHub 账号',
          win.panel.push_button.text() == '绑定 GitHub 账号',
          win.panel.push_button.text())
    check('状态卡片 = 未绑定账号',
          win.panel._status_title.text() == '未绑定账号', win.panel._status_title.text())
    check('左栏没有受管理的文件夹',
          win.sidebar.managed_tree.topLevelItemCount() == 0)
    check('左栏空态提示可见', not win.sidebar._managed_empty.isHidden())

    # ───────────────── 2. 绑定账号 ─────────────────
    print('\n[2] 绑定账号后（未纳管）')
    acct = ghauth.Account(login='tester', name='Tester', id=42)
    bound = account_mod.bind(acct, 'gho_FAKE_TOKEN_FOR_TEST_0123456789')
    check('账号落盘成功', bound.persisted)
    win._account = account_mod.session()
    win._refresh_all()
    check('Push 按钮 = 纳入 GitHub 管理',
          win.panel.push_button.text() == '纳入 GitHub 管理',
          win.panel.push_button.text())
    check('按钮可点', win.panel.push_button.isEnabled())
    check('面板头部显示出已连接的账号',
          win.panel._account_chip.text() == '@tester'
          and not win.panel._account_chip.isHidden(),
          win.panel._account_chip.text())
    check('未纳管时说明里点出文件夹名',
          '笔记文件夹' in win.panel._status_desc.text(),
          win.panel._status_desc.text())

    # ───────────────── 3. 纳管对话框 ─────────────────
    print('\n[3] 纳管对话框')
    dlg = ManageFolderDialog(folder, preselect=['第一篇.txt'], parent=win)
    check('列出了文件夹里的文本文件', set(dlg._files) ==
          {'第一篇.txt', '第二篇.txt', '密码备份.txt'}, str(dlg._files))
    check('预勾选只选中传入的那一篇', dlg._checked == {'第一篇.txt'},
          str(dlg._checked))
    check('计数正确', dlg._sel_count.text() == '已选 1 / 共 3', dlg._sel_count.text())
    check('默认在第 1 步', dlg._stack.currentIndex() == 0)
    check('第 1 步没有「上一步」按钮', dlg._btn_back.isHidden())
    check('构造后「全选」框是未勾状态（因为只选了 1 个）',
          not dlg._cb_all.isChecked())
    dlg._cb_all.setChecked(True)
    dlg._toggle_all()
    check('全选后 3 个都勾上', dlg._checked == set(dlg._files), str(dlg._checked))
    check('全选后计数更新', dlg._sel_count.text() == '已选 3 / 共 3',
          dlg._sel_count.text())

    dlg._cb_all.setChecked(False)
    dlg._toggle_all()
    check('取消全选后一个都不勾', not dlg._checked)
    check('一个都没勾时「下一步」不可点', not dlg._btn_next.isEnabled())
    for name in ('第一篇.txt', '第二篇.txt'):
        dlg._on_row_toggle(name, True)
        dlg._rows[name].set_checked(True)
    check('重新勾选两篇', dlg._checked == {'第一篇.txt', '第二篇.txt'},
          str(dlg._checked))

    dlg._go(1)
    check('切到第 2 步', dlg._stack.currentIndex() == 1)
    check('第 2 步出现「上一步」', not dlg._btn_back.isHidden())
    check('副标题是步骤 2/2', '步骤 2 / 2' in dlg._subtitle.text(),
          dlg._subtitle.text())

    dlg._repo.setText('看不懂的东西')
    check('仓库地址看不懂时不放行', dlg._build_group() is None)
    check('并且给出了报错提示', not dlg._err.isHidden())

    for spec, want in [
        ('https://github.com/freedom0213/FreePushNote-test1.git',
         'freedom0213/FreePushNote-test1'),
        ('freedom0213/FreePushNote-test1', 'freedom0213/FreePushNote-test1'),
        ('git@github.com:freedom0213/FreePushNote-test1.git',
         'freedom0213/FreePushNote-test1'),
        ('https://github.com/freedom0213/FreePushNote-test1/',
         'freedom0213/FreePushNote-test1'),
    ]:
        check(f'仓库地址解析：{spec[:40]}',
              config.parse_repo_spec(spec) == want, str(config.parse_repo_spec(spec)))

    dlg._repo.setText('https://github.com/tester/demo-notes')
    group = dlg._build_group()
    check('合法输入能产出分组', group is not None,
          str(group) if group is None else '')
    if group:
        check('分组 folder 正确', group['folder'] == str(folder))
        check('分组 repo 收敛为 owner/name', group['repo'] == 'tester/demo-notes',
              group['repo'])
        check('白名单只含勾选的两篇',
              group['files'] == ['第一篇.txt', '第二篇.txt'], str(group['files']))
        check('自动生成了 slug 形式的 id', bool(group['id']), str(group['id']))
        check('默认开启站点', group['site'] is True)
    dlg.reject()

    # ───────────────── 4. 落库后的界面 ─────────────────
    print('\n[4] 落库后左栏 / 状态栏 / 按钮')
    win._reload_cfg()
    config.upsert_group(win._cfg, group)
    config.save(win._cfg)
    win._refresh_all()

    check('左栏出现 1 个受管理分组',
          win.sidebar.managed_tree.topLevelItemCount() == 1)
    top = win.sidebar.managed_tree.topLevelItem(0)
    check('分组名是文件夹名', top.text(0) == '笔记文件夹', top.text(0))
    check('分组下有 2 篇文件', top.childCount() == 2, str(top.childCount()))
    check('左栏空态提示消失', win.sidebar._managed_empty.isHidden())
    check('状态栏归属显示分组与仓库',
          '笔记文件夹' in win.statusbar._owner.text()
          and 'tester/demo-notes' in win.statusbar._owner.text(),
          win.statusbar._owner.text())
    check('右栏仓库卡片显示仓库名',
          win.panel._repo_name.text() == 'tester/demo-notes',
          win.panel._repo_name.text())
    check('Push 按钮 = Push 到 GitHub',
          win.panel.push_button.text() == 'Push 到 GitHub',
          win.panel.push_button.text())
    check('推送前 is_pushed 为 None（还没建工作区）',
          pipeline.is_pushed(group, '第一篇.txt') is None)

    # ───────────────── 5. 推送对话框 + 真的推 ─────────────────
    print('\n[5] 推送（本地裸仓库当远端）')
    real_ensure = gitops.ensure_remote

    def local_remote(path, repo, on_log=None):
        url = bare.as_uri()
        if gitops.remote_url(path) != url:
            gitops.git(path, 'remote', 'remove', 'origin', check=False)
            gitops.git(path, 'remote', 'add', 'origin', url)
        return url

    gitops.ensure_remote = local_remote
    try:
        staged = pipeline.stage_group(group, account=account_mod.info(),
                                      on_log=lambda *_a: None)
        check('暂存成功', staged.ok, staged.detail)
        check('暂存后工作区在 workspaces/<id>',
              staged.workspace == config.workspace_dir(group))
        check('用户的笔记文件夹里没有 .git', not (folder / '.git').exists())

        pdlg = PushDialog(group, staged, win)
        check('推送对话框列出 2 篇有改动的笔记',
              set(pdlg._notes) == {'第一篇.txt', '第二篇.txt'}, str(pdlg._notes))
        check('默认全部勾选', pdlg._checked == set(pdlg._notes))
        check('默认提交信息已生成', bool(pdlg._msg.text()), pdlg._msg.text())
        check('站点产物被算成自动产物', bool(staged.artifact_paths),
              str(staged.artifact_paths))
        check('笔记的页面被归到它自己名下',
              any(p.endswith('.md') for p in staged.note_paths['第二篇.txt']),
              str(staged.note_paths))

        pdlg._accept()
        check('keep 里含笔记原文与页面',
              '第一篇.txt' in pdlg.keep and '第二篇.txt' in pdlg.keep,
              str(pdlg.keep))
        check('keep 里含站点产物',
              all(a in pdlg.keep for a in staged.artifact_paths))

        res = pipeline.finalize_push(group, staged, message='首次推送',
                                     token='fake-token', keep=pdlg.keep,
                                     retries=1, on_log=lambda *_a: None)
        check('推送成功', res.ok, f'{res.reason} / {res.message} / {res.detail}')

        tree = bare_tree(bare)
        check('远端有勾选的笔记原文', '第一篇.txt' in tree and '第二篇.txt' in tree)
        check('远端有站点入口', 'index.html' in tree)
        check('未勾选的文件没有上传', '密码备份.txt' not in tree, str(tree))

        win._refresh_all()
        check('推送后按钮变「已是最新，无需推送」',
              win.panel.push_button.text() == '已是最新，无需推送',
              win.panel.push_button.text())
        check('推送后状态卡片 = 已同步',
              win.panel._status_title.text() == '已同步', win.panel._status_title.text())
        check('推送后 is_pushed 为真', pipeline.is_pushed(group, '第一篇.txt') is True)
        check('右栏「最近推送」读到了真实提交',
              win.panel._history_box.count() > 0, str(win.panel._history_box.count()))

        # ───────────────── 6. 改动后 → 待推送 ─────────────────
        print('\n[6] 改一篇之后')
        (folder / '第一篇.txt').write_text(NOTE_A + '\n补了一行。\n',
                                           encoding='utf-8', newline='\r\n')
        win.load_path(str(folder / '第一篇.txt'))
        win._refresh_all()
        check('改动后 is_pushed 为假', pipeline.is_pushed(group, '第一篇.txt') is False)
        check('改动后按钮回到 Push 到 GitHub',
              win.panel.push_button.text() == 'Push 到 GitHub',
              win.panel.push_button.text())
        check('改动后状态卡片 = 有改动待推送',
              win.panel._status_title.text() == '有改动待推送',
              win.panel._status_title.text())

        # ───────────────── 7. 只推选中 ─────────────────
        print('\n[7] 取消勾选一篇 → 它不该被提交')
        (folder / '第二篇.txt').write_text(NOTE_B + '\n也补了一行。\n',
                                           encoding='utf-8')
        staged2 = pipeline.stage_group(group, account=account_mod.info(),
                                       on_log=lambda *_a: None)
        check('两篇都识别为有改动', set(staged2.note_paths) ==
              {'第一篇.txt', '第二篇.txt'}, str(staged2.note_paths))

        pdlg2 = PushDialog(group, staged2, win)
        pdlg2._on_toggle('第二篇.txt', False)
        pdlg2._rows['第二篇.txt'].set_checked(False)
        check('取消勾选后只选了一篇', pdlg2._checked == {'第一篇.txt'},
              str(pdlg2._checked))
        pdlg2._accept()
        check('keep 里不含被取消的那篇',
              '第二篇.txt' not in pdlg2.keep
              and not any(p.endswith('第二篇.md') for p in pdlg2.keep),
              str(pdlg2.keep))

        res2 = pipeline.finalize_push(group, staged2, message='只推第一篇',
                                      token='fake-token', keep=pdlg2.keep,
                                      retries=1, on_log=lambda *_a: None)
        check('推送成功（子集）', res2.ok, f'{res2.reason} / {res2.detail}')
        check('远端第一篇是新内容', '补了一行。' in (bare_show(bare, '第一篇.txt') or ''))
        check('远端第二篇保持旧内容（没被推上去）',
              '也补了一行。' not in (bare_show(bare, '第二篇.txt') or ''))

        # ───────────────── 8. 失败路径回填 ─────────────────
        print('\n[8] 失败状态回填')
        win._push_failed('网络连接中断，改动已保存在本地。', 'URLError: timeout')
        check('失败后状态卡片 = 推送失败',
              win.panel._status_title.text() == '推送失败', win.panel._status_title.text())
        check('失败后按钮 = 重试推送',
              win.panel.push_button.text() == '重试推送', win.panel.push_button.text())
        check('失败后状态栏也是失败',
              '推送失败' in win.statusbar._sync_text.text(),
              win.statusbar._sync_text.text())
        check('失败后按钮仍可点', win.panel.push_button.isEnabled())

        # ───────────────── 9. 未纳管的另一种情形 ─────────────────
        print('\n[9] 同文件夹里没被勾选的文件')
        win.load_path(str(folder / '密码备份.txt'))
        win._refresh_all()
        check('未纳管的文件按钮 = 纳入 GitHub 管理',
              win.panel.push_button.text() == '纳入 GitHub 管理',
              win.panel.push_button.text())
        check('未纳管文件的状态说明提到分组名',
              '笔记文件夹' in win.panel._status_desc.text(),
              win.panel._status_desc.text())
    finally:
        gitops.ensure_remote = real_ensure

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
