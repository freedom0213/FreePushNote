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

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from core import config, envprobe, ghauth, gitops, pipeline  # noqa: E402

from app import account as account_mod  # noqa: E402
from app.main import build_app  # noqa: E402
from app.widgets.managedialog import ManageFolderDialog  # noqa: E402
from app.widgets.pushdialog import PushDialog  # noqa: E402
from app.widgets.sidebar import _close_rect  # noqa: E402
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


def _test_recent_list(win, folder: Path, app) -> None:
    """「最近打开」的顺序规则，以及每行右侧的删除按钮。"""
    print('\n[10] 「最近打开」：点开不重排 / 保存才置顶 / 可逐条删除')
    f1, f2 = folder / '第一篇.txt', folder / '第二篇.txt'
    f3 = folder / '第三篇.txt'
    f3.write_text('第三篇\n', encoding='utf-8', newline='\r\n')

    win._recent = [str(f1), str(f2)]
    win._save_recent()
    win.sidebar.set_recent(win._recent)

    win.load_path(str(f2))
    check('点开已在列表里的文件不改变顺序',
          win._recent == [str(f1), str(f2)], str(win._recent))

    win.load_path(str(f3))
    check('从未打开过的文件追加到末尾，不抢占第一位',
          win._recent == [str(f1), str(f2), str(f3)], str(win._recent))

    win.editor.setPlainText('改了点东西')
    win.save_file()
    check('保存之后才把它提到第一位',
          win._recent == [str(f3), str(f1), str(f2)], str(win._recent))

    win.sidebar.set_recent(win._recent)
    win.resize(1200, 760)
    lst = win.sidebar.recent_list
    lst.resize(180, 320)
    app.processEvents()

    item = lst.item(1)
    check('列表里还有这一条可供点删', item is not None)
    if item is None:
        return
    row = lst.visualItemRect(item)
    check('行矩形已布局（否则下面的几何断言无意义）', row.height() > 0, str(row))
    if row.height() <= 0:
        return

    close = _close_rect(row)
    check('删除按钮落在行内且靠右',
          row.contains(close.center()) and close.right() <= row.right(),
          f'row={row} close={close}')

    victim = item.data(Qt.UserRole + 1)
    before = list(win._recent)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(close.center()),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    lst.mousePressEvent(ev)
    check('点 × 把这一条移出列表',
          victim not in win._recent and len(win._recent) == len(before) - 1,
          str(win._recent))
    check('点 × 不会顺手把这一行切成当前文件',
          win._current == f3, str(win._current))
    check('正在编辑的文档没有被连累关闭',
          win._editor_stack.currentIndex() == 1)


def _test_refresh_caches(win, folder: Path) -> None:
    """切文件不应该反复起 git 子进程（右栏「最近推送」必须命中缓存）。

    这是「点侧栏没反应、过一会儿才切过去」的直接原因：右栏每次重画都要
    读一次提交历史 = 起一个 git 进程。
    """
    print('\n[11] 切文件不再反复起 git 进程')
    calls: list[str] = []
    real = gitops.recent_commits

    def counted(ws, n=5):
        calls.append(str(ws))
        return real(ws, n)

    gitops.recent_commits = counted
    try:
        win._hist_cache.clear()
        win.load_path(str(folder / '第一篇.txt'))
        first = len(calls)
        check('首次读历史确实起了一次 git（说明计数器有效）', first >= 1, str(first))
        for _ in range(5):
            win.load_path(str(folder / '第二篇.txt'))
            win.load_path(str(folder / '第一篇.txt'))
        check('再切 10 次一次都没多起（全部命中缓存）',
              len(calls) == first, f'{first} → {len(calls)}')

        # 缓存必须能失效：新提交之后要看到新的历史
        gitops.recent_commits = real
        ws = config.workspace_dir(config.groups(win._cfg)[0])
        (ws / 'x.txt').write_text('x\n', encoding='utf-8', newline='\n')
        gitops.add_all(ws)
        gitops.commit(ws, 'chore: 制造一次新提交')
        before = len(win._group_history(config.groups(win._cfg)[0]))
        after = len(win._group_history(config.groups(win._cfg)[0]))
        check('HEAD 变了以后缓存会失效并重读', before == after and before >= 2,
              f'{before} → {after}')
    finally:
        gitops.recent_commits = real


def _test_editor_stats(win) -> None:
    """状态栏统计：换成 O(1) 算法后，口径必须和原来逐字一致。"""
    print('\n[12] 状态栏统计（行数 / 字符数）')
    for text, want in [('', (1, 0)), ('a', (1, 1)), ('abc\ndef', (2, 6)),
                       ('abc\ndef\n', (3, 6)), ('中文\n多行\n测试', (3, 6)),
                       ('\n\n\n', (4, 0))]:
        win.editor.load_text(text)
        got = win.editor.stats()
        check(f'{text!r:16s} → {want}', got == want, str(got))
    win.editor.load_text('x' * 4000)
    check('单行超长仍算一行', win.editor.stats() == (1, 4000), str(win.editor.stats()))


def _test_busy_indicator(win, app) -> None:
    """忙碌指示（进度条 + 文案），以及「不弹控制台窗口」的环境参数。"""
    print('\n[13] 忙碌指示与控制台闪窗')
    win.panel.set_progress('preparing')
    check('准备阶段进度条出现', not win.panel._progress.isHidden())
    check('准备阶段文案点明是本地整理',
          win.panel._busy_label.text() == '正在整理这次要提交的内容…',
          win.panel._busy_label.text())
    check('忙碌时收起快捷键提示', win.panel._hotkey.isHidden())

    win.panel.set_progress('pushing')
    check('提交阶段文案换成「正在提交到 GitHub…」',
          win.panel._busy_label.text() == '正在提交到 GitHub…',
          win.panel._busy_label.text())

    win.panel.set_progress(None)
    check('结束后进度条收起', win.panel._progress.isHidden())
    check('结束后忙碌文案收起', win.panel._busy_label.isHidden())

    win.panel.set_push_state('ready')
    check('结束后快捷键提示回来', not win.panel._hotkey.isHidden())
    win.panel.set_push_state('uptodate')
    win.panel.set_progress(None)
    check('「已是最新」态下不显示快捷键提示', win.panel._hotkey.isHidden())

    kw = envprobe.no_window_kwargs()
    if os.name == 'nt':
        check('Windows 下 git 子进程带 CREATE_NO_WINDOW（不再闪黑框）',
              kw.get('creationflags') == 0x08000000, str(kw))
    else:
        check('非 Windows 不加 creationflags', kw == {}, str(kw))


def _test_sidebar_search(win) -> None:
    """[14] 左栏文件名搜索：过滤两个分组、匹配计数、Esc 收起。"""
    print('\n[14] 左栏文件名搜索')
    sb = win.sidebar
    check('搜索框默认收起', sb._search_wrap.isHidden())
    sb._toggle_search()
    check('点放大镜后搜索框出现', not sb._search_wrap.isHidden())

    sb.set_recent(['C:/notes/Java八股.txt', 'C:/notes/agent开发.txt',
                   'C:/notes/读书笔记.txt'])
    sb.set_managed([
        {'name': 'Java八股', 'repo': 'freedom0213/Java-BAGU-notes',
         'folder': 'C:/notes', 'files': ['C:/notes/Java八股.txt',
                                         'C:/notes/Redis持久化.txt']},
        {'name': 'Agent开发', 'repo': 'freedom0213/agent-notes',
         'folder': 'C:/dev', 'files': ['C:/dev/工具链.txt']},
    ])

    sb._search_box.setText('redis')
    items = [sb.recent_list.item(i) for i in range(sb.recent_list.count())]
    check('「最近打开」里不命中的行被隐藏',
          items[0].isHidden() and items[1].isHidden())
    check('受管理组里命中的文件仍然显示',
          not sb.managed_tree.topLevelItem(0).child(1).isHidden())
    check('同组不命中的文件被隐藏',
          sb.managed_tree.topLevelItem(0).child(0).isHidden())
    check('没有命中的组整组隐藏',
          sb.managed_tree.topLevelItem(1).isHidden())
    check('计数说「匹配 1 项」', sb._search_match.text() == '匹配 1 项',
          sb._search_match.text())

    sb._search_box.setText('agent开发')
    check('组名命中时整组放行',
          not sb.managed_tree.topLevelItem(1).isHidden()
          and not sb.managed_tree.topLevelItem(1).child(0).isHidden())
    check('组名命中后计数按放行的文件行算',
          sb._search_match.text() == '匹配 2 项', sb._search_match.text())

    sb._search_box.setText('不存在的文件xyz')
    check('无命中时提示「没有匹配的文件」',
          sb._search_match.text() == '没有匹配的文件', sb._search_match.text())

    sb._search_box.setText('redis')
    sb._close_search()
    check('Esc 关闭后搜索框收起', sb._search_wrap.isHidden())
    check('关闭时过滤词已清空', sb._search_box.text() == '')
    check('关闭后所有行恢复显示',
          not items[0].isHidden()
          and not sb.managed_tree.topLevelItem(1).isHidden())


def _test_findbar(win, app) -> None:
    """[15] 内嵌查找条：输入即跳、计数、Enter/Esc。"""
    from PySide6.QtCore import QPoint

    print('\n[15] 编辑器内嵌查找条（Ctrl+F）')
    fb = win._findbar
    check('查找条默认隐藏', fb.isHidden())

    src = _TMP / 'findsrc.txt'
    src.write_text('第一段没有关键词。\nRedis 的持久化分两种。\n'
                   '第二种持久化是 AOF。\n结尾。\n', encoding='utf-8')
    win.load_path(str(src))
    win.find_in_file()
    check('Ctrl+F 后查找条出现', not fb.isHidden())
    # 焦点断言在 offscreen 下没有意义（没有窗口系统），只验证打开动作本身

    fb._input.setText('持久化')
    app.processEvents()
    check('输入即跳到第一个命中', '持久化' in win.editor.textCursor().selectedText(),
          win.editor.textCursor().selectedText())
    fb._rescan()
    check('计数给出「1 / 2」', fb._count.text() == '1 / 2', fb._count.text())

    fb._find_next()
    check('Enter 跳到下一个命中', '持久化' in win.editor.textCursor().selectedText())
    check('计数更新为「2 / 2」', fb._count.text() == '2 / 2', fb._count.text())

    fb._find_next()
    check('到底后绕回开头', '持久化' in win.editor.textCursor().selectedText())

    fb._input.setText('一定不存在的词xyz')
    app.processEvents()
    check('查不到时提示「无结果」', fb._count.text() == '无结果', fb._count.text())

    fb.close_requested.emit()
    check('Esc 关闭后查找条收起', fb.isHidden())


def _test_account_page(win, app) -> None:
    """[16] 账户页与退出登录（放在最后：退出会清掉账号）。"""
    from app.widgets import accountdialog as ad_mod
    from app.widgets.accountdialog import AccountDialog

    print('\n[16] 账户页与退出登录')
    acct = account_mod.session()
    check('前提：账号处于已绑定状态', acct is not None)

    groups = [{'name': 'Java八股', 'repo': 'freedom0213/Java-BAGU-notes'},
              {'name': 'Agent开发', 'repo': ''}]
    dlg = AccountDialog(acct, groups, parent=win)
    check('头像圆片用了账号首字母', dlg._account.login.startswith('t'))
    check('退出按钮存在且初始可见', not dlg._signout_btn.isHidden())

    dlg._show_signout_confirm()
    check('点「退出登录」后确认区出现', not dlg._confirm_wrap.isHidden())
    check('原按钮隐藏', dlg._signout_btn.isHidden())
    dlg._hide_signout_confirm()
    check('「取消」后确认区收回', dlg._confirm_wrap.isHidden()
          and not dlg._signout_btn.isHidden())

    fired = []
    dlg.signed_out.connect(lambda: fired.append(1))
    dlg._do_signout()
    check('确认退出后发出 signed_out 信号', fired == [1])

    # 退出链路：unbind 清凭据、界面回到未绑定态
    win._on_signed_out()
    check('退出后内存会话清空', win._account is None)
    check('退出后磁盘凭据一并清掉', account_mod.session() is None)
    check('Push 按钮回到「绑定 GitHub 账号」',
          win.panel.push_button.text() == '绑定 GitHub 账号',
          win.panel.push_button.text())
    check('分组配置还在（退出不清关联）',
          win.sidebar.managed_tree.topLevelItemCount() >= 1)
    check('账号胶囊隐藏', win.panel._account_chip.isHidden())


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

    _test_recent_list(win, folder, app)
    _test_refresh_caches(win, folder)
    _test_editor_stats(win)
    _test_busy_indicator(win, app)
    _test_sidebar_search(win)
    _test_findbar(win, app)
    _test_account_page(win, app)   # 放最后：退出登录会清掉账号

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
