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

def push_group(group: dict, *, message: str | None = None,
               names: list[str] | None = None,
               token: str | None = None,
               account: dict | None = None,
               retries: int = 3, on_log=None) -> PushResult:
    """把分组推送上去。**不抛异常**，所有失败都收进 :class:`PushResult`。

    ``names`` 为 None 时推全部分组内的受管理文件（设计稿 S-01 里可勾选子集）。
    ``token`` 缺失时不推送 —— 用本机 gh 凭据是开发期的退路，正式链路必须带令牌。
    """
    log = on_log or (lambda *_a, **_k: None)
    picked = list(names if names is not None else config.managed_names(group))
    if not picked:
        return PushResult(reason=REASON_NO_FILES,
                          message='这个分组里还没有纳入管理的文件。')

    if not group.get('repo'):
        return PushResult(reason=REASON_NO_REMOTE, message='还没有关联 GitHub 仓库。')
    if not token:
        return PushResult(reason=REASON_NO_REMOTE,
                          message='还没有绑定 GitHub 账号，无法推送。')

    try:
        ws = prepare_workspace(group, on_log=log)
    except (gitops.GitError, OSError) as exc:
        return PushResult(reason=REASON_GIT_ERROR,
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
        return PushResult(reason=REASON_NO_FILES,
                          message='勾选的文件都读不到，本次没有可推送的内容。',
                          warnings=warnings)

    site_stats = None
    try:
        site_stats = build_site(group, pages, on_log=log)
    except (OSError, ValueError) as exc:
        # 站点生成失败不该拦住原文推送：笔记原文才是用户真正丢不起的东西
        warnings.append(f'站点生成失败，已只推送原文：{exc}')
        log(f'!! 站点生成失败：{exc}')

    if not gitops.has_changes(ws):
        return PushResult(ok=True, reason=REASON_NO_CHANGES,
                          message='本地内容与 GitHub 一致，没有需要推送的改动。',
                          files=picked, warnings=warnings, site_stats=site_stats)

    commit_message = (message or '').strip() or config.default_commit_message(
        group, picked)
    try:
        gitops.add_all(ws)
        gitops.commit(ws, commit_message)
    except gitops.GitError as exc:
        return PushResult(reason=REASON_GIT_ERROR,
                          message='本地提交失败。', detail=str(exc),
                          warnings=warnings, site_stats=site_stats)

    sha = gitops.short_hash(ws)
    log(f'已提交 {sha}：{commit_message}')

    try:
        ok, attempts = gitops.push(ws, token=token, retries=retries, on_log=log)
    except (gitops.GitError, OSError) as exc:
        return PushResult(reason=REASON_PUSH_FAILED, commit=sha,
                          message='推送失败，改动已保存在本地。', detail=str(exc),
                          files=picked, warnings=warnings, site_stats=site_stats)

    if not ok:
        return PushResult(reason=REASON_PUSH_FAILED, commit=sha,
                          message='推送失败，改动已保存在本地，可以重试。',
                          files=picked, warnings=warnings, site_stats=site_stats,
                          attempts=attempts)

    return PushResult(ok=True, reason=REASON_OK, commit=sha,
                      message=f'已推送 {sha}', files=picked, warnings=warnings,
                      site_stats=site_stats, attempts=attempts)


def detect_new_files(group: dict) -> list[str]:
    """扫描源文件夹，找出「还没纳入管理」的笔记文件（设计稿 S-02）。

    解决的是「我明明新建了个 txt，怎么没同步」——用户不会记得自己当初勾了哪些。
    """
    managed = set(config.managed_names(group))
    return [n for n in config.scan_notes(str(group.get('folder') or ''))
            if n not in managed]
