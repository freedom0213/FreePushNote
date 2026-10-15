# -*- coding: utf-8 -*-
"""离屏 UI 截图：不开真窗口，直接把界面渲染成 PNG，用于开发期自查布局。

用法（在 pushnote 目录下）::

    .venv\\Scripts\\python.exe tools\\uishot.py [输出目录]

走 ``QT_QPA_PLATFORM=offscreen``，不需要真实屏幕，也不会弹窗打断你。
配置目录会重定向到临时目录，**不会碰 ~/.pushnote 里的真实配置**。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 必须在导入 PySide6 之前设置。
# 默认走 offscreen（安静、不需要屏幕），但 offscreen 下 Qt 的字体库是空的，
# 中文会渲染成方块 —— 要验证真实字体请加 --live（窗口会被挪到屏幕外）。
if '--live' not in sys.argv:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('PUSHNOTE_HOME', str(Path(tempfile.gettempdir()) / 'pushnote_uitest'))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402

from core import ghauth, gitops, pipeline  # noqa: E402

from app.main import build_app  # noqa: E402
from app.widgets.authdialog import GitHubAuthDialog  # noqa: E402
from app.window import FreePushWindow  # noqa: E402

SAMPLE = """16：Spring 的 IoC 容器是什么？

IoC 是 Inversion of Control，控制反转。它把对象的创建与依赖装配交给容器统一
管理，对象自己不再负责 new 依赖对象。

可以这样理解：以前是自己做饭，现在改成了点外卖——你需要什么，容器就给你什么，
你不用关心中间是怎么做出来的。

容器主要做这三件事：
  1. 扫描并注册 BeanDefinition
  2. 按依赖关系完成实例化与属性注入
  3. 管理完整生命周期：初始化、使用、销毁

常见实现有两种：BeanFactory 是懒加载，用到才创建；ApplicationContext 在启动时
就预实例化，功能更全，日常开发中用得最多。

30：软换行的行号测试

下面这一段是一整行、中间没有任何换行符的长文本，用来验证窗口变窄时续行的行号位置会有一个淡色小点——这一段会一直写下去直到它必然超过窗口宽度为止，这样才能看清续行的效果以及它的标记。
"""


def main() -> int:
    live = '--live' in sys.argv
    positional = [a for a in sys.argv[1:] if not a.startswith('--')]
    out_dir = Path(positional[0]) if positional else Path(tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)

    app = build_app([])
    win = FreePushWindow()
    win.resize(1200, 760)
    if live:
        win.move(-4000, -4000)      # 挪出可见区域，不打扰正在用电脑的人
    win.show()

    produced: list[Path] = []
    holder: dict = {}

    def shoot(name: str) -> None:
        app.processEvents()
        path = out_dir / name
        win.grab().save(str(path))
        produced.append(path)

    def shoot_manage_and_push() -> None:
        """纳管对话框与推送对话框。

        真造一个笔记文件夹 + 本地裸仓库当远端，走**真实暂存**拿到变更清单 ——
        截图里的 +N −M 是真数字，不是摆拍。
        """
        from app.widgets.managedialog import ManageFolderDialog
        from app.widgets.pushdialog import PushDialog

        base = out_dir / 'dialog_demo'
        folder = base / '笔记文件夹'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / '第一篇.txt').write_text(
            '第一篇笔记\n\n第一行要点。\n第二行要点。\n\n新的一段。\n',
            encoding='utf-8', newline='\r\n')
        (folder / '第二篇.txt').write_text(
            '===== 集合 =====\n\n1：ArrayList 和 LinkedList 的区别？\n\n'
            '  一个数组，一个链表。\n', encoding='utf-8')
        (folder / '密码备份.txt').write_text('不该上传的内容\n', encoding='utf-8')

        mng = ManageFolderDialog(folder, preselect=['第一篇.txt'], parent=win)
        mng.setModal(False)
        mng.show()
        app.processEvents()
        p = out_dir / 'ui_08_manage_1.png'
        mng.grab().save(str(p))
        produced.append(p)

        mng._go(1)
        mng._repo.setText('freedom0213/FreePushNote-test1')
        app.processEvents()
        p = out_dir / 'ui_09_manage_2.png'
        mng.grab().save(str(p))
        produced.append(p)
        group = mng._build_group()
        mng.reject()
        if group is None:
            return

        # 真实走一遍暂存（不联网：远端换成本地裸仓库）
        bare = base / 'remote.git'
        bare.mkdir(parents=True, exist_ok=True)
        gitops.git(bare, 'init', '--bare', '-b', 'main', check=False)
        real_ensure = gitops.ensure_remote

        def local_remote(path, repo, on_log=None):
            url = bare.as_uri()
            if gitops.remote_url(path) != url:
                gitops.git(path, 'remote', 'remove', 'origin', check=False)
                gitops.git(path, 'remote', 'add', 'origin', url)
            return url

        gitops.ensure_remote = local_remote
        try:
            staged = pipeline.stage_group(
                group, account={'login': 'freedom0213', 'id': 184794503},
                on_log=lambda *_a: None)
        finally:
            gitops.ensure_remote = real_ensure

        if staged.ok and staged.has_changes:
            pdlg = PushDialog(group, staged, win)
            pdlg.setModal(False)
            pdlg.show()
            app.processEvents()
            p = out_dir / 'ui_10_push.png'
            pdlg.grab().save(str(p))
            produced.append(p)
            pdlg.reject()

    def shoot_dialog() -> None:
        """认证对话框：等待态 + 失败态。

        对话框会真去申请一次设备码（只申请、不授权，无副作用），
        这样才能验证「验证码真的显示出来」而不是画个假的。
        """
        dlg = holder['dlg']
        app.processEvents()
        p1 = out_dir / 'ui_06_bind.png'
        dlg.grab().save(str(p1))
        produced.append(p1)

        # 失败态不走真网络：直接调用失败分支，验证文案与按钮是否对
        dlg._countdown.stop()
        dlg._show_error(ghauth.KIND_NETWORK, '连不上 GitHub',
                        'URLError: [WinError 10061] connection refused')
        app.processEvents()
        p2 = out_dir / 'ui_07_bind_error.png'
        dlg.grab().save(str(p2))
        produced.append(p2)

        dlg.reject()
        shoot_manage_and_push()
        for p in produced:
            print(p)
        app.quit()

    def shoot_recent_and_busy() -> None:
        """左栏「最近打开」的悬停删除按钮，以及推送中的忙碌指示。

        悬停状态是手工设进列表里的（``_set_hover``）—— 离屏环境没有真实鼠标，
        但 delegate 读的就是这个字段，所以画出来的和用户真正划过时是同一套代码。
        """
        demo = out_dir / 'recent_demo'
        demo.mkdir(parents=True, exist_ok=True)
        paths = []
        for n in ('Java八股2.txt', 'agent开发八股.txt', '读书笔记.txt',
                  'Redis补充.txt'):
            f = demo / n
            f.write_text(f'{n} 的内容\n', encoding='utf-8', newline='\n')
            paths.append(str(f))

        win.load_path(paths[0])
        win._recent = list(paths)
        win.sidebar.set_recent(win._recent)
        win.sidebar.highlight_recent(paths[0])
        app.processEvents()

        lst = win.sidebar.recent_list
        # 鼠标停在第二行上：该行露出 ×，当前编辑的那一行本来就有 ×
        lst._set_hover(paths[1], False)
        app.processEvents()
        p = out_dir / 'ui_11_recent_delete.png'
        lst.grab().save(str(p))
        produced.append(p)

        # 鼠标正压在 × 上：加深成实心反馈
        lst._set_hover(paths[1], True)
        app.processEvents()
        p = out_dir / 'ui_12_recent_close_hover.png'
        lst.grab().save(str(p))
        produced.append(p)

        # 推送中：按钮暗蓝 + 细进度条 + 「正在提交到 GitHub…」
        win.panel.set_push_state('running')
        win.panel.set_sync_state('running')
        win.panel.set_progress('pushing')
        app.processEvents()
        p = out_dir / 'ui_13_busy.png'
        win.panel._progress.parentWidget().grab().save(str(p))
        produced.append(p)
        win.panel.set_progress(None)
        win.panel.set_push_state('disabled')
        win.panel.set_sync_state('unmanaged')

    def shoot_new_features() -> None:
        """三个新界面：侧栏文件名搜索 / 内嵌查找条 / 账户页。"""
        from app import account as account_mod
        from app.widgets.accountdialog import AccountDialog

        # ── 侧栏搜索：点开放大镜，输入一个只命中部分文件的词 ──
        sb = win.sidebar
        sb._toggle_search()
        sb._search_box.setText('Redis')
        app.processEvents()
        p = out_dir / 'ui_14_sidebar_search.png'
        win.grab().save(str(p))
        produced.append(p)
        sb._close_search()

        # ── 内嵌查找条：Ctrl+F，输入即跳到第一个命中 ──
        win.find_in_file()
        win._findbar._input.setText('容器')
        app.processEvents()
        p = out_dir / 'ui_15_findbar.png'
        win.grab().save(str(p))
        produced.append(p)
        win._findbar.close_requested.emit()

        # ── 账户页：用假账号（PUSHNOTE_HOME 已重定向，不碰真实配置）──
        acct = account_mod.bind(
            ghauth.Account(login='freedom0213', name='freedom', id=1),
            'gho_FAKE_TOKEN_FOR_SHOT')
        groups = [{'name': 'Java八股', 'repo': 'freedom0213/Java-BAGU-notes'},
                  {'name': 'Agent开发', 'repo': 'freedom0213/agent-notes'}]
        dlg = AccountDialog(acct, groups, parent=win)
        dlg.setModal(False)
        dlg.show()
        app.processEvents()
        p = out_dir / 'ui_16_account.png'
        dlg.grab().save(str(p))
        produced.append(p)

        dlg._show_signout_confirm()
        app.processEvents()
        p = out_dir / 'ui_17_account_confirm.png'
        dlg.grab().save(str(p))
        produced.append(p)
        dlg.reject()

    def shoot_notice_and_diff() -> None:
        """统一提示框（三态）+ 差异窗口 + 账号胶囊悬停。"""
        from app.widgets.diffdialog import DiffDialog
        from app.widgets.notice import NoticeDialog

        # 账号胶囊：先让界面上有账号，再手工置成悬停态
        win._refresh_all()
        chip = win.panel._account_chip
        chip.set_account('freedom0213')
        chip.setVisible(True)
        chip._hover = True
        chip._restyle()
        app.processEvents()
        p = out_dir / 'ui_21_chip_hover.png'
        win.panel.grab().save(str(p))
        produced.append(p)
        chip._hover = False
        chip._restyle()

        shots = [
            ('ui_18_notice_info.png',
             dict(title='无需推送', kind='info',
                  body='本地内容与 GitHub 上的一致，没有需要推送的改动。')),
            ('ui_19_notice_success.png',
             dict(title='推送完成（有提醒）', kind='success',
                  body='已推送 2 个文件。\n\n· Java八股2.txt：本地是 GBK 编码，'
                       '仓库里已转成 UTF-8')),
            ('ui_20_notice_error.png',
             dict(title='推送失败', kind='error', ok_text='重试推送',
                  body='推送失败，改动已保存在本地，可以重试。\n\n'
                       '改动已保存在本地，不会丢失。修好后可以直接重试。',
                  detail='fatal: unable to access https://github.com/freedom0213/'
                         'FreePushNote-test1.git/\n'
                         'Recv failure: Connection was reset (10054)')),
        ]
        # 首次对接的提示（文案来自真实函数，不另抄一份 —— 否则截图会失真）
        from app.window import remote_ahead_prompt
        _t, _b, _ok = remote_ahead_prompt({'behind': 9, 'first_time': True})
        shots.append(('ui_27_remote_first.png',
                      dict(title=_t, body=_b, kind='info',
                           ok_text=_ok, cancel_text='稍后再说')))
        for name, kwargs in shots:
            dlg = NoticeDialog(win, **kwargs)
            dlg.setModal(False)
            dlg.show()
            app.processEvents()
            p = out_dir / name
            dlg.grab().save(str(p))
            produced.append(p)
            dlg.reject()

        rows = [
            {'name': 'Java八股2.txt', 'added': 3, 'removed': 1,
             'text': '--- 仓库 · Java八股2.txt\n'
                     '+++ 本地 · Java八股2.txt\n'
                     '@@ -1,4 +1,6 @@\n'
                     ' 16：Spring 的 IoC 容器是什么？\n'
                     ' \n'
                     '-容器负责创建对象。\n'
                     '+IoC 是 Inversion of Control，控制反转。它把对象的创建与依赖装配\n'
                     '+交给容器统一管理。\n'
                     '+对象自己不再负责 new 依赖对象。\n'
                     ' \n'
                     ' 常见实现有两种。'},
            {'name': 'Redis补充.txt', 'added': 2, 'removed': 0,
             'text': '--- 仓库 · Redis补充.txt\n'
                     '+++ 本地 · Redis补充.txt\n'
                     '@@ -3,3 +3,5 @@\n'
                     ' RDB 是快照。\n'
                     '+AOF 记的是写命令日志。\n'
                     '+两种可以同时开。'},
        ]
        dd = DiffDialog(rows, win)
        dd.setModal(False)
        dd.show()
        app.processEvents()
        p = out_dir / 'ui_22_diff.png'
        dd.grab().save(str(p))
        produced.append(p)
        dd.reject()

    def shoot_pull() -> None:
        """拉取确认层：三组清单 + 备份说明。"""
        from app.widgets.pulldialog import PullDialog
        from core import pipeline
        from core.pipeline import PullFile, PullPlan

        plan = PullPlan(ok=True, reason=pipeline.REASON_OK, ahead=0, behind=3,
                        remote_rev='origin/main',
                        files=[PullFile('Java八股2.txt', 'update', '本地没改过，直接用远端版本'),
                               PullFile('Redis补充.txt', 'update', '本地没改过，直接用远端版本'),
                               PullFile('agent开发.txt', 'merge', '两边改的位置不重叠，已自动合并'),
                               PullFile('读书笔记.txt', 'conflict', '1 处两边改到了同一位置')],
                        outside=['Java八股2.md', 'index.html', 'README.md',
                                 '_sidebar.md'])
        dlg = PullDialog(plan, win)
        dlg.setModal(False)
        dlg.show()
        app.processEvents()
        p = out_dir / 'ui_23_pull.png'
        dlg.grab().save(str(p))
        produced.append(p)
        dlg.reject()

    def shoot_settings() -> None:
        """设置页（V3-09）：账号 / 受管理的文件夹 / 推送行为 / 关于 四张卡片。"""
        from app import account as account_mod
        from app.widgets.settingsdialog import SettingsDialog

        win._refresh_all()
        # 喂一个假分组，让「受管理的文件夹」卡片有东西可看
        demo = {'id': 'shotgrp', 'name': 'Java八股笔记',
                'folder': r'C:\Users\freedom\Desktop\Java笔记',
                'repo': 'freedom0213/Java-BAGU-notes', 'branch': 'main',
                'files': ['Java八股.txt', 'Redis补充.txt', 'MySQL锁.txt']}
        dlg = SettingsDialog(win._cfg, account_mod.session(), [demo], parent=win)
        dlg.setModal(False)
        dlg.show()
        app.processEvents()
        p = out_dir / 'ui_24_settings.png'
        dlg.grab().save(str(p))
        produced.append(p)
        dlg.reject()

    def shoot_newfiles() -> None:
        """S-02：推送前发现未纳入管理的文件（460px 提示面板）。"""
        from app.widgets.newfilesdialog import NewFilesDialog

        files = [{'name': 'Redis八股.txt', 'mtime': 1759831200.0},
                 {'name': '分布式锁笔记.txt', 'mtime': 1759747800.0}]
        demo = {'id': 'shotgrp', 'name': 'Java八股笔记',
                'folder': r'C:\Users\freedom\Desktop\Java笔记'}
        dlg = NewFilesDialog(files, demo, win)
        dlg.setModal(False)
        dlg.show()
        app.processEvents()
        p = out_dir / 'ui_25_newfiles.png'
        dlg.grab().save(str(p))
        produced.append(p)
        dlg.reject()

    def shoot_history() -> None:
        """提交历史窗口（两栏）+ 工具栏的「关闭」按钮。"""
        from app.widgets.historydialog import HistoryDialog

        group = {'id': 'demo', 'name': '示例分组',
                 'repo': 'freedom0213/FreePushNote-test2', 'branch': 'main'}
        dlg = HistoryDialog(group, win)
        sha = 'b0b75e4' + '0' * 33
        dlg.set_commits({
            'ok': True, 'reason': 'ok', 'rev': 'HEAD', 'message': '',
            'commits': [
                {'sha': sha, 'short': 'b0b75e4', 'when': '10-13 19:49',
                 'author': 'freedom0213', 'message': '更新 验收笔记A'},
                {'sha': 'e5def28' + '0' * 33, 'short': 'e5def28',
                 'when': '10-13 19:41', 'author': 'freedom0213',
                 'message': 'test2'},
                {'sha': '765dc12' + '0' * 33, 'short': '765dc12',
                 'when': '10-13 19:27', 'author': 'freedom0213',
                 'message': '更新 验收笔记A'},
            ]})
        # 用真实的 git show 输出过一遍 _tidy_patch，截图才等于用户看到的样子
        from core import pipeline as _pl
        dlg.set_patch(sha, _pl._tidy_patch(
            'diff --git a/验收笔记A.txt b/验收笔记A.txt\n'
            'index 8c1f2ab..b0b75e4 100644\n'
            '--- a/验收笔记A.txt\n'
            '+++ b/验收笔记A.txt\n'
            '@@ -6,3 +6,5 @@\n'
            ' （这一篇会纳入 GitHub 管理。）\n'
            '+1\n'
            '+2\n'))
        dlg.setModal(False)
        dlg.show()
        app.processEvents()
        p = out_dir / 'ui_28_history.png'
        dlg.grab().save(str(p))
        produced.append(p)
        dlg.reject()

        win.toolbar.grab().save(str(out_dir / 'ui_29_toolbar.png'))
        produced.append(out_dir / 'ui_29_toolbar.png')

    def shoot_push_policy() -> None:
        """P0 修复后的推送确认层（删什么 / 保住什么）+ 状态栏琥珀胶囊 + S-03 卡。"""
        from types import SimpleNamespace
        from app.widgets.pushdialog import PushDialog
        from app.widgets.healthdialog import EncodingHealthDialog

        group = {'id': 'demo', 'name': 'Java八股笔记',
                 'repo': 'freedom0213/Java-BAGU-notes', 'branch': 'main',
                 'files': ['Java八股2.txt']}
        # 用 SimpleNamespace 造一个"整理结果"：数字是摆拍，分组结构是真的
        staged = SimpleNamespace(
            ok=True, reason='ok', message='', detail='',
            workspace=None, files=['Java八股2.txt'],
            changes=[{'path': 'Java八股2.txt', 'name': 'Java八股2.txt',
                      'added': 12, 'removed': 3},
                     {'path': 'Java八股2.md', 'name': 'Java八股2.md',
                      'added': 40, 'removed': 8},
                     {'path': 'LICENSE', 'name': 'LICENSE', 'added': 0, 'removed': 21},
                     {'path': 'tools/sync.py', 'name': 'sync.py', 'added': 0, 'removed': 12}],
            note_paths={'Java八股2.txt': ['Java八股2.txt', 'Java八股2.md']},
            artifact_paths=['index.html', '_sidebar.md'],
            removed=['代码片段.txt', '代码片段.md'],
            untouched=['LICENSE', 'tools/sync.py', 'requirements.txt'],
            warnings=[], site_stats=None, has_changes=True,
            total_added=52, total_removed=11)
        dlg = PushDialog(group, staged, win)
        dlg.setModal(False)
        dlg.show()
        app.processEvents()
        p = out_dir / 'ui_30_push_policy.png'
        dlg.grab().save(str(p))
        produced.append(p)
        dlg.reject()

        # ── 状态栏：GBK + CRLF 都异常 → 两颗琥珀胶囊 ──
        win.statusbar.set_encoding('GBK', warn=True)
        win.statusbar.set_eol('CRLF', warn=True)
        app.processEvents()
        win.statusbar.grab().save(str(out_dir / 'ui_31_statusbar.png'))
        produced.append(out_dir / 'ui_31_statusbar.png')

        # ── S-03 体检卡 ──
        card = EncodingHealthDialog(encoding_key='gbk', encoding_name='GBK',
                                    eol_key='crlf', eol_name='CRLF', parent=win)
        card.setModal(False)
        card.show()
        app.processEvents()
        p = out_dir / 'ui_32_health.png'
        card.grab().save(str(p))
        produced.append(p)
        card.reject()
        # 还原状态栏，别让后面的截图带着警告
        win.statusbar.set_encoding('UTF-8', warn=False)
        win.statusbar.set_eol('LF', warn=False)
    def shoot_welcome() -> None:
        """V3-10：什么都还没开始时的欢迎态（对比 V3-11 的日常空态）。

        真实第一跑就是这个样子：没账号、没分组、没最近文件。
        为了截图**诚实**，连配置都临时指向一个空配置 —— 否则左栏右栏会显示
        「用过之后」的内容，跟欢迎态自相矛盾。
        """
        from core import config as cfg_mod

        blank = out_dir / 'shot_blank_config.json'
        cfg_mod.save(cfg_mod.blank_config(), blank)
        saved = (win._account, win._recent, win._cfg, win._cfg_stamp,
                 cfg_mod.CONFIG_PATH)
        try:
            cfg_mod.CONFIG_PATH = blank
            win._account = None
            win._recent = []
            win._cfg_stamp = None         # 置空 -> 强制重读，读到那份空配置
            win._refresh_all()
            # 左栏「最近打开」不在 _refresh_all 里重建（平时只在开/关文件时变），
            # 这里得显式喂一次，否则截图会留着上一次的列表。
            win.sidebar.set_recent(win._recent)
            shoot('ui_26_welcome.png')
        finally:
            (win._account, win._recent, win._cfg, win._cfg_stamp,
             cfg_mod.CONFIG_PATH) = saved
            win._refresh_all()

    def run() -> None:
        shoot_welcome()                             # 欢迎态（V3-10）
        shoot('ui_01_empty.png')                    # 日常空态（V3-11）

        sample = out_dir / 'ui_sample.txt'
        sample.write_text(SAMPLE, encoding='utf-8', newline='\r\n')
        win.load_path(str(sample))
        shoot('ui_02_editing.png')                  # 正常编辑态（含行号）

        win.toggle_panel(False)                     # 右栏收成窄条
        shoot('ui_03_rail.png')

        win.toggle_panel(True)
        win.toggle_sidebar()                        # 左栏收起
        shoot('ui_04_no_sidebar.png')

        win.toggle_sidebar()                        # 再展开回来
        win.editor.set_font_size(22)                # 等价于 Ctrl+滚轮放大
        shoot('ui_05_zoom.png')
        win.editor.set_font_size(16)

        shoot_recent_and_busy()
        shoot_new_features()
        shoot_notice_and_diff()
        shoot_pull()
        shoot_settings()
        shoot_newfiles()
        shoot_history()
        shoot_push_policy()

        dlg = GitHubAuthDialog(win)
        dlg.setModal(False)
        dlg.show()
        dlg.start()
        holder['dlg'] = dlg
        QTimer.singleShot(3000, shoot_dialog)

    QTimer.singleShot(700, run)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
