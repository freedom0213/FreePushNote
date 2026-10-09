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

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import config, convert, gitops, site

#: 推送结果的种类。界面按种类给不同文案 —— 不共用一句「推送失败」
REASON_OK = 'ok'
REASON_NO_FILES = 'no_files'          # 一个文件都没勾
REASON_NO_CHANGES = 'no_changes'      # 本地与远端一致
REASON_NO_REMOTE = 'no_remote'        # 没配远程仓库
REASON_GIT_ERROR = 'git_error'        # init / commit 阶段出错
REASON_PUSH_FAILED = 'push_failed'    # 网络 / 授权 / 冲突


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
