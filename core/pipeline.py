# -*- coding: utf-8 -*-
"""推送链路：本地笔记文件夹 → GitHub 仓库（可选附带 docsify 站点）。

为什么工作区是隔离的
------------------
用户的笔记文件夹里**只有被勾选的文件**会被复制到工作区，然后在工作区里
提交、推送。由此得到两个性质：

* 用户文件夹里不会出现 ``.git``，也不会多出任何生成物（决定 #4）
* 「不想公开的文件不会上传」不靠自觉，而是**那些文件根本没被复制过去** ——
  物理上做不到泄露

工作区固定在 ``~/.pushnote/workspaces/<分组 id>/``，是软件自己的地盘，
每次推送前整块清空重建，所以「取消勾选」的文件会真的从仓库里消失。

仓库里的布局::

    <仓库根>/
      <笔记>.txt        原样备份，但统一转成 UTF-8 + LF（GitHub 上能正常显示）
      index.html        docsify 入口        ┐
      README.md         首页                │ site=True 时才有
      _sidebar.md       侧栏目录            │
      <slug>.md         每篇一页            ┘
      .nojekyll
      assets/*          本地化的前端资源

站点默认直接放仓库根：GitHub Pages 默认就从根目录发布，用户不用再去改仓库设置。
"""
from __future__ import annotations

import difflib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, convert, gitops, site, textio

#: 推送结果的种类。界面按种类给不同文案 —— 不共用一句「推送失败」
REASON_OK = 'ok'
REASON_NO_FILES = 'no_files'          # 一个文件都没勾
REASON_NO_CHANGES = 'no_changes'      # 本地与远端一致
REASON_NO_REMOTE = 'no_remote'        # 没配远程仓库
REASON_GIT_ERROR = 'git_error'        # init / commit 阶段出错
REASON_PUSH_FAILED = 'push_failed'    # 网络 / 授权 / 冲突
REASON_UP_TO_DATE = 'up_to_date'      # 远端没有新东西
REASON_LOCAL_AHEAD = 'local_ahead'    # 本地有还没推出去的提交
REASON_FETCH_FAILED = 'fetch_failed'  # 读不到远端（网络 / 授权）
REASON_CONFLICT = 'conflict'          # 有文件两边都改了同一处
REASON_ARTIFACTS_ONLY = 'artifacts_only'  # 远端的新提交只动了自动生成的站点文件


@dataclass
class PushResult:
    ok: bool = False
    reason: str = REASON_GIT_ERROR
    message: str = ''
    detail: str = ''
    commit: str = ''
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    site_stats: dict | None = None
    attempts: int = 0


@dataclass
class StageResult:
    """「已经同步到工作区、但还没提交」的中间态。"""

    ok: bool = False
    reason: str = REASON_GIT_ERROR
    message: str = ''
    detail: str = ''
    workspace: Path | None = None
    files: list[str] = field(default_factory=list)
    #: 逐文件的增删行数：``[{'path','name','added','removed'}, ...]``
    changes: list[dict] = field(default_factory=list)
    #: 笔记名 → 它涉及的所有仓库内路径（原文 + 生成的页面）
    note_paths: dict[str, list[str]] = field(default_factory=dict)
    #: 站点自动产物（首页 / 侧栏 / index.html / assets/*），不单独提供开关
    artifact_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    site_stats: dict | None = None
    has_changes: bool = False

    @property
    def total_added(self) -> int:
        return sum(int(c.get('added', 0)) for c in self.changes)

    @property
    def total_removed(self) -> int:
        return sum(int(c.get('removed', 0)) for c in self.changes)


# ─────────────────────────── 工作区 ───────────────────────────

def workspace_dir(group: dict) -> Path:
    return config.workspace_dir(group)


def _assert_inside_workspaces(path: Path) -> None:
    """只允许清空 ``~/.pushnote/workspaces/`` 底下的目录。

    分组 id 已经过 slug 校验，正常不可能越界；但这一步是**删除操作的最后一道闸**，
    代价只有一行，出问题时能救命。
    """
    root = config.WORKSPACES_DIR.resolve()
    target = path.resolve()
    if target == root or root not in target.parents:
        raise ValueError(f'拒绝操作工作区之外的路径：{target}')


def clear_workspace(ws: Path) -> None:
    """清空工作区里除 ``.git`` 以外的一切。

    整块重建而不是增量比对，是为了让「取消勾选的文件」真的从仓库里消失 ——
    否则用户以为撤下来了，其实文件还挂在公开仓库上。
    """
    _assert_inside_workspaces(ws)
    if not ws.is_dir():
        return
    for item in ws.iterdir():
        if item.name == '.git':
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass


def prepare_workspace(group: dict, on_log=None) -> Path:
    """确保工作区存在、是 git 仓库、并且 origin 指向目标仓库。"""
    ws = workspace_dir(group)
    ws.mkdir(parents=True, exist_ok=True)
    if not gitops.is_repo(ws):
        gitops.init_repo(ws, branch=str(group.get('branch') or 'main'), on_log=on_log)
    if group.get('repo'):
        gitops.ensure_remote(ws, str(group['repo']), on_log=on_log)
    return ws


# ─────────────────────────── 内容 ───────────────────────────

def _plain_note_to_md(text: str) -> str:
    """普通笔记（不匹配章节格式）→ Markdown。

    只做一件有意义的加工：把单换行变成硬换行。
    用户写笔记的习惯是「一行一个要点」，而 Markdown 会把单换行合并成一段，
    不加这一步，整篇笔记在网页上会糊成一大坨。**不改写任何文字**。
    """
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return '\n'.join(site.harden_breaks(lines)).strip() + '\n'


def materialize(group: dict, names: list[str], ws: Path,
                on_log=None) -> tuple[list[dict], list[str]]:
    """把白名单里的源文件复制进工作区，并准备出站点页面数据。

    返回 ``(pages, warnings)``。单个文件读不了只记警告、不中断整次推送 ——
    为了一个坏文件让整批笔记推不上去，是更糟的选择。
    """
    log = on_log or (lambda *_a, **_k: None)
    folder = Path(str(group.get('folder') or ''))
    pages: list[dict] = []
    warnings: list[str] = []

    for name in names:
        src = folder / name
        if not src.is_file():
            warnings.append(f'{name}：源文件不存在，已跳过')
            continue
        try:
            text, encoding = convert.read_text_auto(src)
        except convert.NoteFormatError as exc:
            warnings.append(f'{name}：{exc}')
            continue

        # 备份一份进仓库：统一 UTF-8 + LF，这样 GBK 的笔记在 GitHub 上也能正常显示
        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        (ws / name).write_text(normalized, encoding='utf-8', newline='\n')

        mode = convert.detect_mode(text)
        markdown = convert.convert(text) if mode == 'site' else _plain_note_to_md(text)
        pages.append({
            'source': name,
            'title': Path(name).stem,
            'markdown': markdown,
            'mode': mode,
        })
        if encoding not in ('utf-8', 'utf-8-sig'):
            warnings.append(f'{name}：本地是 {encoding.upper()} 编码，'
                            f'仓库里已转成 UTF-8')

    log(f'已同步 {len(pages)} 个文件到工作区')
    return pages, warnings


def build_site(group: dict, pages: list[dict], on_log=None) -> dict | None:
    """按分组的站点开关生成 docsify 站点。"""
    if not group.get('site') or not pages:
        return None
    title = str(group.get('site_title') or group.get('name') or '我的笔记')
    return site.build_notes_site(
        pages, config.docs_path(group),
        title=title,
        desc=f'{title} · 由 FreePushNote 自动生成',
        on_log=on_log,
    )


# ─────────────────────────── 主流程 ───────────────────────────
#
# 分两阶段，是为了让界面能在「真正推出去之前」把这次会改哪些文件、
# 各增删多少行拿给用户看（设计稿 S-01）。第一阶段全是本地操作、不联网：
#
#     stage_group()      同步文件 → 生成站点 → git add → 读出逐文件增删行数
#     finalize_push()    用户确认提交信息后 → commit → push
#
# :func:`push_group` 是两者的薄封装，行为与拆分前完全一致（测试都指向它）。


def stage_group(group: dict, *, names: list[str] | None = None,
                account: dict | None = None, on_log=None) -> 'StageResult':
    """第一阶段：把内容同步进工作区并暂存，返回真实变更清单。**不联网。**"""
    log = on_log or (lambda *_a, **_k: None)
    picked = list(names if names is not None else config.managed_names(group))
    if not picked:
        return StageResult(reason=REASON_NO_FILES,
                           message='这个分组里还没有纳入管理的文件。')
    if not group.get('repo'):
        return StageResult(reason=REASON_NO_REMOTE, message='还没有关联 GitHub 仓库。')

    try:
        ws = prepare_workspace(group, on_log=log)
    except (gitops.GitError, OSError) as exc:
        return StageResult(reason=REASON_GIT_ERROR,
                           message='准备工作区失败。', detail=str(exc))

    if account and account.get('login'):
        try:
            gitops.ensure_identity_for_account(
                ws, str(account['login']), account.get('id'), on_log=log)
        except gitops.GitError as exc:
            log(f'!! 设置提交身份失败：{exc}')

    clear_workspace(ws)
    pages, warnings = materialize(group, picked, ws, on_log=log)
    if not pages:
        return StageResult(reason=REASON_NO_FILES,
                           message='勾选的文件都读不到，本次没有可推送的内容。',
                           warnings=warnings)

    site_stats = None
    try:
        site_stats = build_site(group, pages, on_log=log)
    except (OSError, ValueError) as exc:
        # 站点生成失败不该拦住原文推送：笔记原文才是用户真正丢不起的东西
        warnings.append(f'站点生成失败，已只推送原文：{exc}')
        log(f'!! 站点生成失败：{exc}')

    try:
        gitops.add_all(ws)
        changes = gitops.staged_numstat(ws)
    except gitops.GitError as exc:
        return StageResult(reason=REASON_GIT_ERROR, message='暂存改动失败。',
                           detail=str(exc), warnings=warnings, site_stats=site_stats)

    note_paths, artifact_paths = _split_changes(changes, picked, site_stats)
    return StageResult(ok=True, workspace=ws, files=picked, changes=changes,
                       has_changes=bool(changes), warnings=warnings,
                       site_stats=site_stats, note_paths=note_paths,
                       artifact_paths=artifact_paths)


def _split_changes(changes: list[dict], picked: list[str],
                   site_stats: dict | None) -> tuple[dict[str, list[str]], list[str]]:
    """把变更清单分成「属于哪篇笔记」和「站点自动产物」两组。

    界面要让用户按**笔记**来勾选，而不是按一堆生成的 ``.md`` / ``assets/*``。
    所以这里把每篇笔记自己（``x.txt``）和它的页面（``<slug>.md``）归到一起，
    其余（首页 / 侧栏 / index.html / 资源）算自动产物，不单独提供开关。
    """
    slugs = (site_stats or {}).get('slugs') or {}
    page_owner = {f'{slug}.md': src for src, slug in slugs.items()}
    note_set = set(picked)

    note_paths: dict[str, list[str]] = {}
    artifact_paths: list[str] = []
    for c in changes:
        name, path = c.get('name', ''), c.get('path', '')
        if name in note_set:
            note_paths.setdefault(name, []).append(path)
        elif page_owner.get(Path(path).name):
            note_paths.setdefault(page_owner[Path(path).name], []).append(path)
        else:
            artifact_paths.append(path)
    return note_paths, artifact_paths


def finalize_push(group: dict, staged: 'StageResult', *, message: str | None = None,
                  token: str | None = None, keep: list[str] | None = None,
                  retries: int = 3, on_log=None) -> PushResult:
    """第二阶段：提交并推送。

    ``keep`` 给定时只提交这些**仓库内路径**的改动（设计稿 S-01 的勾选）。
    没被列入的文件会被移出暂存区，**但内容仍留在工作区**，下次推送再带上 ——
    而不是把它从仓库里删掉。

    注意这里收的是「路径」而不是「文件名」：一次推送的变更清单里既有用户勾选的
    笔记，也有自动生成的站点产物（``index.html`` / ``<名字>.md`` / ``assets/*``），
    后者跟着笔记走、不可单独取消。
    """
    log = on_log or (lambda *_a, **_k: None)

    if not token:
        return PushResult(reason=REASON_NO_REMOTE,
                          message='还没有绑定 GitHub 账号，无法推送。',
                          files=staged.files, warnings=staged.warnings,
                          site_stats=staged.site_stats)
    if not staged.ok or staged.workspace is None:
        return PushResult(reason=staged.reason, message=staged.message,
                          detail=staged.detail, files=staged.files,
                          warnings=staged.warnings, site_stats=staged.site_stats)
    if not staged.has_changes:
        return PushResult(ok=True, reason=REASON_NO_CHANGES,
                          message='本地内容与 GitHub 一致，没有需要推送的改动。',
                          files=staged.files, warnings=staged.warnings,
                          site_stats=staged.site_stats)

    ws = staged.workspace

    if keep is not None:
        keep_set = {str(p) for p in keep}
        skip = [c['path'] for c in staged.changes if c['path'] not in keep_set]
        try:
            gitops.unstage(ws, skip)
        except gitops.GitError as exc:
            log(f'!! 取消暂存失败：{exc}')
        if not gitops.has_staged_changes(ws):
            return PushResult(ok=True, reason=REASON_NO_CHANGES,
                              message='选中的文件没有需要推送的改动。',
                              files=staged.files, warnings=staged.warnings,
                              site_stats=staged.site_stats)

    commit_message = (message or '').strip() or config.default_commit_message(
        group, staged.files)
    try:
        gitops.commit(ws, commit_message)
    except gitops.GitError as exc:
        return PushResult(reason=REASON_GIT_ERROR, message='本地提交失败。',
                          detail=str(exc), files=staged.files,
                          warnings=staged.warnings, site_stats=staged.site_stats)

    sha = gitops.short_hash(ws)
    log(f'已提交 {sha}：{commit_message}')

    try:
        ok, attempts = gitops.push(ws, token=token, retries=retries, on_log=log)
    except (gitops.GitError, OSError) as exc:
        return PushResult(reason=REASON_PUSH_FAILED, commit=sha,
                          message='推送失败，改动已保存在本地。', detail=str(exc),
                          files=staged.files, warnings=staged.warnings,
                          site_stats=staged.site_stats)

    if not ok:
        return PushResult(reason=REASON_PUSH_FAILED, commit=sha,
                          message='推送失败，改动已保存在本地，可以重试。',
                          files=staged.files, warnings=staged.warnings,
                          site_stats=staged.site_stats, attempts=attempts)

    return PushResult(ok=True, reason=REASON_OK, commit=sha,
                      message=f'已推送 {sha}', files=staged.files,
                      warnings=staged.warnings, site_stats=staged.site_stats,
                      attempts=attempts)


def push_group(group: dict, *, message: str | None = None,
               names: list[str] | None = None,
               token: str | None = None,
               account: dict | None = None,
               retries: int = 3, on_log=None) -> PushResult:
    """一步推完（暂存 + 提交 + 推送）。**不抛异常**，失败都收进 :class:`PushResult`。

    界面走两阶段（先给用户看变更再推），命令行 / 自动推送用这个更省事。
    """
    picked = list(names if names is not None else config.managed_names(group))
    if not picked:
        return PushResult(reason=REASON_NO_FILES,
                          message='这个分组里还没有纳入管理的文件。')
    if not group.get('repo'):
        return PushResult(reason=REASON_NO_REMOTE, message='还没有关联 GitHub 仓库。')
    if not token:
        return PushResult(reason=REASON_NO_REMOTE,
                          message='还没有绑定 GitHub 账号，无法推送。')

    staged = stage_group(group, names=picked, account=account, on_log=on_log)
    return finalize_push(group, staged, message=message, token=token,
                         retries=retries, on_log=on_log)


def detect_new_files(group: dict) -> list[str]:
    """扫描源文件夹，找出「还没纳入管理」的笔记文件（设计稿 S-02）。

    解决的是「我明明新建了个 txt，怎么没同步」——用户不会记得自己当初勾了哪些。
    """
    managed = set(config.managed_names(group))
    return [n for n in config.scan_notes(str(group.get('folder') or ''))
            if n not in managed]


def is_pushed(group: dict, name: str) -> bool | None:
    """这一篇本地内容是否与**上一次提交（也就是上次推上来的东西）**一致。

    必须比 HEAD 而不是比工作区的工作树：暂存（stage）会把工作区刷成和源文件
    一模一样，那时比工作树会误报「已同步」——而它其实还没提交、更没推出去。

    不需要联网就能给出诚实结论。返回 ``None`` 表示判断不了
    （工作区还没建过 / 源文件读不了），这时界面**不要**硬报「已同步」。
    """
    ws = config.workspace_dir(group)
    if not gitops.is_repo(ws) or not gitops.head_exists(ws):
        return None

    src = Path(str(group.get('folder') or '')) / name
    if not src.is_file():
        return None
    try:
        text, _encoding = convert.read_text_auto(src)
    except convert.NoteFormatError:
        return None

    proc = gitops.git(ws, 'show', f'HEAD:{Path(name).name}', check=False)
    if proc.returncode != 0:
        return False        # 仓库里还没有这个文件 → 肯定没推过
    # 这里**不能**用 stdout_of（它会 strip），尾随换行也是内容的一部分
    committed = (proc.stdout or b'').decode('utf-8', errors='replace')
    return committed == text


# ─────────────────────────── 差异预览 ───────────────────────────

def _head_text(ws: Path, name: str) -> str:
    """仓库里 ``name`` 现在的内容（上一次提交的版本）；没有则空串。"""
    if not gitops.is_repo(ws) or not gitops.head_exists(ws):
        return ''
    # quotepath：中文文件名默认会被 git 转义成 \346\212\200 这种形式，
    # 那样 ``HEAD:<name>`` 就找不到文件了。只作用于这一条命令。
    proc = gitops.git(ws, '-c', 'core.quotepath=false',
                      'show', f'HEAD:{Path(name).name}', check=False)
    if proc.returncode != 0:
        return ''
    return (proc.stdout or b'').decode('utf-8', errors='replace')


def diff_preview(group: dict, *, names: list[str] | None = None) -> list[dict]:
    """预览「这次推送到底会改什么」：仓库里的版本 ↔ 本地现在的样子。

    不需要联网，也不要求先走过一遍推送流程 —— 旧版直接从工作区的 git 历史里
    取，新版把本地笔记按**推送时完全相同的规则**归一化（自动识别编码 + 统一
    LF），所以界面上看到的增删就是推上去之后真实发生的增删，不是另算一套。

    返回 ``[{'name','added','removed','text'}, ...]``，**只含真有差异的文件**；
    全部一致时返回空列表（界面据此说「没有未推送的改动」，而不是弹一个空白窗）。
    """
    folder = Path(str(group.get('folder') or ''))
    ws = workspace_dir(group)
    picked = list(names if names is not None else config.managed_names(group))

    out: list[dict] = []
    for name in picked:
        src = folder / name
        if not src.is_file():
            continue
        try:
            text, _encoding = convert.read_text_auto(src)
        except convert.NoteFormatError:
            continue

        new = text.replace('\r\n', '\n').replace('\r', '\n')
        old = _head_text(ws, name)
        if old == new:
            continue

        lines: list[str] = []
        added = removed = 0
        for line in difflib.unified_diff(
                old.splitlines(), new.splitlines(),
                fromfile=f'仓库 · {name}', tofile=f'本地 · {name}',
                lineterm='', n=2):
            lines.append(line)
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1

        out.append({'name': name, 'added': added, 'removed': removed,
                    'text': '\n'.join(lines)})
    return out


# ─────────────────────────── 拉取（Pull） ───────────────────────────
#
# 与推送同构地分两阶段：
#
#     plan_pull()   读远端 → 判 ahead/behind → 定 base → 逐篇比对 / 试合并
#                   **只算不写**，把「会更新几篇、哪篇会冲突」先拿给用户看
#     apply_pull()  备份 → 按原编码写回笔记 → 中转区追平远端
#
# 三条不可动摇的规则：
#
#   1. 本地**没改过**的文件才直接覆盖；改过的走三方合并（各改各的能自动合掉）；
#      两边改到同一处则**不写**，把选择权交回用户
#   2. 写回一律保持该文件**原本的编码与换行符** —— 不能让一篇 GBK+CRLF 的
#      笔记被悄悄改成 UTF-8+LF，别的工具会因此认不出来
#   3. 写回前先备份到 ``~/.pushnote/backups/``；备份失败就**不动文件**

#: 备份保留份数。备份是保险，不是归档。
BACKUP_KEEP = 5


@dataclass
class PullFile:
    """一篇笔记在本次拉取里的处置。``action``: update | merge | conflict | skip"""

    name: str
    action: str
    note: str = ''


@dataclass
class PullPlan:
    """拉取计划（只算不写）。``writes`` 里的内容在 :func:`apply_pull` 才落盘。"""

    ok: bool = False
    reason: str = REASON_GIT_ERROR
    message: str = ''
    detail: str = ''
    ahead: int = 0
    behind: int = 0
    base_rev: str = ''
    remote_rev: str = ''
    files: list[PullFile] = field(default_factory=list)
    #: 笔记名 → 归一化后的新正文（UTF-8 / LF）
    writes: dict[str, str] = field(default_factory=dict)
    #: 笔记名 → (编码, 换行)，写回时按它还原
    original: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: 远端新提交里、**不属于**本次同步范围的路径（自动生成的站点文件等）。
    #: 这些不会被拉回本地，也不该被拉回 —— 但必须让用户知道它们的存在。
    outside: list[str] = field(default_factory=list)

    @property
    def updated(self) -> list[PullFile]:
        return [f for f in self.files if f.action == 'update']

    @property
    def merged(self) -> list[PullFile]:
        return [f for f in self.files if f.action == 'merge']

    @property
    def conflicts(self) -> list[PullFile]:
        return [f for f in self.files if f.action == 'conflict']

    @property
    def has_work(self) -> bool:
        return bool(self.writes) or bool(self.conflicts)


@dataclass
class PullResult:
    ok: bool = False
    reason: str = REASON_GIT_ERROR
    message: str = ''
    detail: str = ''
    written: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    backup_dir: Path | None = None


def _normalize_newlines(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _backup_notes(folder: Path, names: list[str]) -> Path | None:
    """把即将被改写的笔记先复制一份。返回备份目录；失败返回 ``None``。"""
    target = config.BACKUPS_DIR / time.strftime('%Y%m%d-%H%M%S')
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = folder / name
            if src.is_file():
                shutil.copy2(src, target / name)
    except OSError:
        return None
    _prune_backups()
    return target


def _prune_backups(keep: int = BACKUP_KEEP) -> None:
    """只留最近 ``keep`` 次备份。删的是我们自己在 ``~/.pushnote`` 下建的目录。"""
    root = config.BACKUPS_DIR
    if not root.is_dir():
        return
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
    for old in dirs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def check_remote(group: dict, *, token: str | None = None, on_log=None) -> dict:
    """推送前看一眼：远端有没有我们这个分支上没有的提交。

    只 ``fetch`` + 比较计数，**不动任何文件**。返回 ``{'ok','ahead','behind','message'}``。

    ``ok=False`` 表示「没检查成」（没网 / 没授权），不是「远端有新东西」——
    调用方**不要**因此拦住推送：真正的失败留给 push 那一步去报，
    检查失败就拦人，等于断网时连推送都不让试，那是帮倒忙。
    """
    log = on_log or (lambda *_a, **_k: None)
    if not group.get('repo'):
        return {'ok': False, 'ahead': 0, 'behind': 0,
                'message': '还没有关联 GitHub 仓库。'}
    if not token:
        return {'ok': False, 'ahead': 0, 'behind': 0,
                'message': '还没有绑定 GitHub 账号。'}

    try:
        ws = prepare_workspace(group, on_log=log)
    except (gitops.GitError, OSError) as exc:
        return {'ok': False, 'ahead': 0, 'behind': 0, 'message': str(exc)}

    branch = str(group.get('branch') or 'main')
    if not gitops.fetch(ws, branch, token=token, on_log=log):
        return {'ok': False, 'ahead': 0, 'behind': 0,
                'message': '连不上 GitHub，没能确认远端状态。'}

    ahead, behind = gitops.ahead_behind(ws, branch)
    log(f'远端状态：本地领先 {ahead}，落后 {behind}')
    return {'ok': True, 'ahead': ahead, 'behind': behind, 'message': ''}


def plan_pull(group: dict, *, token: str | None = None, on_log=None) -> PullPlan:
    """分析一次拉取：谁会更新、谁要合并、谁冲突。**不改任何文件。**"""
    log = on_log or (lambda *_a, **_k: None)
    picked = config.managed_names(group)
    if not picked:
        return PullPlan(reason=REASON_NO_FILES,
                        message='这个分组里还没有纳入管理的文件。')
    if not group.get('repo'):
        return PullPlan(reason=REASON_NO_REMOTE, message='还没有关联 GitHub 仓库。')
    if not token:
        return PullPlan(reason=REASON_NO_REMOTE,
                        message='还没有绑定 GitHub 账号，无法拉取。')

    try:
        ws = prepare_workspace(group, on_log=log)
    except (gitops.GitError, OSError) as exc:
        return PullPlan(reason=REASON_GIT_ERROR, message='准备工作区失败。',
                        detail=str(exc))

    branch = str(group.get('branch') or 'main')
    if not gitops.fetch(ws, branch, token=token, on_log=log):
        return PullPlan(reason=REASON_FETCH_FAILED,
                        message='连不上 GitHub，读不到远端内容。',
                        detail='检查网络，或确认代理软件正在运行。')

    ahead, behind = gitops.ahead_behind(ws, branch)
    log(f'与远端比较：本地领先 {ahead} 个提交，落后 {behind} 个提交')

    if behind == 0:
        if ahead == 0:
            return PullPlan(ok=True, reason=REASON_UP_TO_DATE, ahead=ahead, behind=behind,
                            message='远端没有新的内容。')
        return PullPlan(ok=True, reason=REASON_LOCAL_AHEAD, ahead=ahead, behind=behind,
                        message='远端没有新内容，但本地有还没推上去的改动。\n'
                                '先推送这些改动，拉取才有意义。')

    remote_rev = f'origin/{branch}'
    if ahead == 0:
        base_rev = 'HEAD'
    else:
        # 分叉：共同祖先不是 HEAD。若拿 HEAD 当 base，远端已有的改动会被
        # 误算成「本地新增」，合并结果直接是错的。
        base_rev = gitops.merge_base(ws, 'HEAD', remote_rev) or 'HEAD'
        log(f'检测到分叉（本地领先 {ahead} 个提交），共同祖先 {base_rev[:8]}')

    folder = Path(str(group.get('folder') or ''))
    files: list[PullFile] = []
    writes: dict[str, str] = {}
    original: dict[str, tuple[str, str]] = {}

    # 远端这段时间改过的所有路径。**这一步是为了把「改了但不同步的东西」说出来** ——
    # 典型场景：用户在 GitHub 网页上直接编辑了自动生成的站点页面（<笔记>.md）。
    # 那个文件每次推送都会按笔记原文重新生成，网页上的改动迟早被覆盖；
    # 如果这里不提，用户只会看到「Pull 成功」而本地毫无变化，然后彻底懵掉。
    changed = gitops.diff_names(ws, f'{base_rev}..{remote_rev}')
    picked_set = set(picked)
    outside = [p for p in changed if p not in picked_set]

    for name in picked:
        src = folder / name
        theirs_raw = gitops.show_file(ws, remote_rev, name)
        if theirs_raw is None:
            files.append(PullFile(name, 'skip', '远端还没有这篇'))
            continue
        if not src.is_file():
            files.append(PullFile(name, 'skip', '本地找不到这个文件'))
            continue

        ours, enc, eol = textio.read_text(src)          # 换行已归一成 \n
        theirs = _normalize_newlines(theirs_raw)
        base = _normalize_newlines(gitops.show_file(ws, base_rev, name) or '')

        # 先看**远端有没有动这篇** —— 它没动，本地改没改都轮不到远端来管。
        # （顺序不能反：两边都没改时若先判 ours == base，会把它错算成
        # 「需要更新」，白写一遍内容还多列一条改动。）
        if theirs == base:
            files.append(PullFile(name, 'skip', '远端没改这篇'))
        elif ours == base:
            files.append(PullFile(name, 'update', '本地没改过，直接用远端版本'))
            writes[name] = theirs
            original[name] = (enc, eol)
        else:
            merged, conflicts = gitops.merge_file(base, ours, theirs)
            if conflicts:
                files.append(PullFile(name, 'conflict',
                                      f'{conflicts} 处两边改到了同一位置'))
            else:
                files.append(PullFile(name, 'merge', '两边改的位置不重叠，已自动合并'))
                writes[name] = merged
                original[name] = (enc, eol)

    if not writes and not any(f.action == 'conflict' for f in files):
        if outside:
            # 远端确实有提交，但改的都不是笔记原文 —— 说白了：改的是成果物。
            # 不能用「已经是最新」这种说法糊过去，用户会觉得软件在骗他。
            return PullPlan(ok=True, reason=REASON_ARTIFACTS_ONLY,
                            ahead=ahead, behind=behind,
                            remote_rev=remote_rev, files=files, outside=outside,
                            message='远端的新提交只改了自动生成的文件。')
        return PullPlan(ok=True, reason=REASON_UP_TO_DATE, ahead=ahead, behind=behind,
                        remote_rev=remote_rev, files=files,
                        message='远端没有新的内容。')

    reason = REASON_CONFLICT if any(f.action == 'conflict' for f in files) else REASON_OK
    return PullPlan(ok=True, reason=reason, ahead=ahead, behind=behind,
                    base_rev=base_rev, remote_rev=remote_rev,
                    files=files, writes=writes, original=original, outside=outside)


def apply_pull(group: dict, plan: PullPlan, *, on_log=None) -> PullResult:
    """执行计划：备份 → 按原编码写回笔记 → 中转区追平远端。"""
    log = on_log or (lambda *_a, **_k: None)
    if not plan.ok:
        return PullResult(reason=plan.reason, message=plan.message, detail=plan.detail)

    result = PullResult(ok=True, reason=plan.reason,
                        conflicts=[f.name for f in plan.conflicts],
                        merged=[f.name for f in plan.merged])
    names = sorted(plan.writes)

    if not names:
        _align_workspace(group, plan.remote_rev, log)
        result.message = plan.message or '没有需要写回本地的内容。'
        return result

    folder = Path(str(group.get('folder') or ''))
    backup = _backup_notes(folder, names)
    if backup is None:
        # 宁可什么都不做，也不在没备份的情况下覆盖用户的笔记
        log('!! 备份失败，已中止写回')
        return PullResult(reason=REASON_GIT_ERROR,
                          message='备份没做成，为安全起见没有改写你的笔记。',
                          detail=f'确认这个目录可写：{config.BACKUPS_DIR}')
    result.backup_dir = backup
    log(f'已备份 {len(names)} 篇到 {backup}')

    for name in names:
        enc, eol = plan.original.get(name, ('utf-8', 'crlf'))
        try:
            textio.write_text(folder / name, plan.writes[name],
                              encoding=enc, eol=eol)
        except OSError as exc:
            result.failed[name] = str(exc)
            log(f'!! 写回 {name} 失败：{exc}')
        else:
            result.written.append(name)
            log(f'已更新 {name}')

    _align_workspace(group, plan.remote_rev, log)

    if result.failed:
        result.ok = False
        result.reason = REASON_GIT_ERROR
        result.message = f'有 {len(result.failed)} 篇没能写回。'
    else:
        result.message = f'已更新 {len(result.written)} 篇笔记。'
        if result.conflicts:
            result.message += f'\n有 {len(result.conflicts)} 篇两边改到了同一处，已保留你的版本。'
    return result


def _align_workspace(group: dict, remote_rev: str, log) -> None:
    """让中转区追平远端，使下一次推送是快进。

    中转区的工作树是临时镜像（每次推送前整块重建），``reset --hard`` 丢弃它
    是安全的；**用户的笔记文件不受影响**。
    """
    if not remote_rev:
        return
    try:
        ws = prepare_workspace(group)
        gitops.reset_hard(ws, remote_rev)
        log(f'中转区已对齐远端（{remote_rev}）')
    except (gitops.GitError, OSError) as exc:
        log(f'!! 中转区对齐失败（不影响本地笔记）：{exc}')
