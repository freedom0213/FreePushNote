# -*- coding: utf-8 -*-
"""绑定关系的读写与校验（v2：文件夹 = 分组 = 一个仓库）。

模型
----
「分组」是唯一的同步单元：

    一个本地文件夹  ↔  一个 GitHub 仓库

分组里维护一份**纳入管理的文件白名单**。文件夹里没被勾选的文件
**永远不会离开这台机器** —— 这是本项目最重要的一条安全边界，
因为用户的笔记文件夹里常常混着不想公开的东西。

    groups: [
      {
        "id": "java-notes",               # slug，用于工作区目录名
        "name": "Java八股",                # 显示名（默认取文件夹名）
        "folder": "D:\\\\笔记\\\\Java八股",    # 本地文件夹（绝对路径）
        "repo": "freedom0213/java-notes",  # owner/name
        "branch": "main",
        "files": ["基础语法.txt", ...],     # 白名单（相对 folder 的文件名）
        "site": true,                     # 是否额外生成 docsify 站点
        "site_title": "Java 八股文笔记",
        "docs_dir": "docs",               # 站点输出目录（仓库内）
        "created_at": "2026-10-09T13:20:00"
      }
    ]

为什么工作区不在用户的笔记文件夹里
--------------------------------
见 :func:`workspace_dir`：推送在一个隔离的工作区里进行，
只把白名单里的文件复制过去。这样带来两个结果

* 用户笔记文件夹里**不会出现 `.git`**（决定 #4：不往用户文件夹塞东西）
* 「不泄露未勾选的文件」不再是靠自觉，而是**物理上做不到** ——
  没被复制的文件根本没机会进入提交

写入方式
--------
临时文件 + ``os.replace`` 的原子替换，避免断电产生半截配置。

v1 兼容
-------
v1 是「单个 txt → 仓库」的模型，字段结构完全不同、无法无损迁移，
且本机从未产生过真实的 v1 数据。读到 v1 时**丢弃并在返回值里说明**，
不做静默转换 —— 静默转换往往比报错更危险。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

# 允许用环境变量 PUSHNOTE_HOME 重定向，便于测试和多套配置共存
_CONFIG_HOME = os.environ.get('PUSHNOTE_HOME')
CONFIG_DIR = Path(_CONFIG_HOME) if _CONFIG_HOME else (Path.home() / '.pushnote')
CONFIG_PATH = CONFIG_DIR / 'config.json'
WORKSPACES_DIR = CONFIG_DIR / 'workspaces'

SCHEMA_VERSION = 2

#: 允许纳入管理的扩展名。**刻意只放文本类** —— 这个软件的存在意义就是 txt。
NOTE_EXTENSIONS = ('.txt', '.md')

DEFAULTS: dict = {
    'branch': 'main',
    'retry': 3,
    'retry_interval': 5,
    # 站点输出目录，相对仓库根。空串 = 直接放仓库根 ——
    # GitHub Pages 默认就是从根目录发布，这样用户不用再改仓库设置。
    'docs_dir': '',
    'commit_template': '更新 {target}',
}

_REPO_RE = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')
_BRANCH_RE = re.compile(r'^[A-Za-z0-9._/-]+$')
_BAD_NAME_CHARS = ('/', '\\', '..')


class ConfigError(ValueError):
    """配置非法（格式错误、路径不存在等）。"""


def blank_config() -> dict:
    return {'version': SCHEMA_VERSION, 'defaults': dict(DEFAULTS), 'groups': []}


def defaults_of(cfg: dict) -> dict:
    merged = dict(DEFAULTS)
    merged.update(cfg.get('defaults') or {})
    return merged


# ───────────────────────────── 读写 ─────────────────────────────

def load(path: Path | str | None = None) -> dict:
    """读取配置；文件不存在时返回空白配置（而不是报错）。"""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return blank_config()
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f'配置文件无法解析：{p}（{exc}）') from exc
    if not isinstance(raw, dict):
        raise ConfigError(f'配置文件根节点必须是对象：{p}')

    cfg = blank_config()
    # 未知键一律保留（比如 github 段），避免将来加字段时互相踩掉
    for key, value in raw.items():
        cfg[key] = value

    items = raw.get('groups')
    if not isinstance(items, list):
        items = []
    cfg['groups'] = [g for g in items if isinstance(g, dict)]

    # v1 是「单文件 → 仓库」，结构无法无损迁移：丢弃并明确记录
    if raw.get('bindings'):
        cfg['_dropped_v1_bindings'] = len(raw['bindings'])
    cfg.pop('bindings', None)
    cfg.pop('active_id', None)
    cfg['version'] = SCHEMA_VERSION
    return cfg


def save(cfg: dict, path: Path | str | None = None) -> Path:
    """原子写入配置，返回落盘路径。"""
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in cfg.items() if not k.startswith('_')}
    clean['version'] = SCHEMA_VERSION
    text = json.dumps(clean, ensure_ascii=False, indent=2) + '\n'
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8', newline='\n')
    os.replace(tmp, p)          # 同一分区上的原子替换
    return p


# ───────────────────────────── 分组 ─────────────────────────────

def groups(cfg: dict) -> list[dict]:
    return cfg.setdefault('groups', [])


def group_by_id(cfg: dict, gid: str | None) -> dict | None:
    if not gid:
        return None
    for g in groups(cfg):
        if g.get('id') == gid:
            return g
    return None


def _norm(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def group_for_path(cfg: dict, path: str | os.PathLike) -> dict | None:
    """找出某个本地文件所属的分组；不属于任何分组时返回 None。

    出现嵌套文件夹时取**路径最长**的那个分组 —— 否则外层会误吞内层。
    """
    target = _norm(path)
    best: dict | None = None
    for g in groups(cfg):
        folder = str(g.get('folder') or '')
        if not folder:
            continue
        base = _norm(folder)
        if target != base and not target.startswith(base + os.sep):
            continue
        if best is None or len(base) > len(_norm(best.get('folder') or '')):
            best = g
    return best


def managed_names(group: dict) -> list[str]:
    """分组内已纳入管理的文件名（保持配置里的顺序）。"""
    return [str(n) for n in (group.get('files') or []) if isinstance(n, str)]


def is_managed(cfg: dict, path: str | os.PathLike) -> bool:
    """这个文件是否「在某个分组里，且被勾选纳入管理」。"""
    g = group_for_path(cfg, path)
    if g is None:
        return False
    return Path(path).name in managed_names(g)


def scan_notes(folder: str | os.PathLike) -> list[str]:
    """扫描文件夹**顶层**的候选笔记文件（按名称排序）。

    刻意不递归：设计稿里「受管理的文件夹」下面是平铺的文件列表，
    加一层嵌套会让左栏的树、勾选弹窗、路径显示都复杂一档。
    将来真需要子目录时，再加 ``recursive`` 开关。
    """
    p = Path(folder)
    if not p.is_dir():
        return []
    items = [f.name for f in p.iterdir()
             if f.is_file() and f.suffix.lower() in NOTE_EXTENSIONS]
    return sorted(items, key=lambda s: s.lower())


def set_files(cfg: dict, group_id: str, names: list[str]) -> dict | None:
    """重设某个分组的白名单（去重、保持顺序）。"""
    g = group_by_id(cfg, group_id)
    if g is None:
        return None
    seen: list[str] = []
    for n in names:
        n = str(n)
        if n not in seen:
            seen.append(n)
    g['files'] = seen
    return g


def upsert_group(cfg: dict, group: dict) -> dict:
    """按 id 新增或覆盖一个分组。"""
    items = groups(cfg)
    for i, g in enumerate(items):
        if g.get('id') == group.get('id'):
            items[i] = group
            break
    else:
        items.append(group)
    return cfg


def remove_group(cfg: dict, group_id: str) -> bool:
    items = groups(cfg)
    keep = [g for g in items if g.get('id') != group_id]
    if len(keep) == len(items):
        return False
    cfg['groups'] = keep
    return True


def make_group_id(cfg: dict, seed: str) -> str:
    """由文件夹名派生一个不重复的 slug。"""
    base = re.sub(r'[^a-z0-9]+', '-', (seed or '').lower()).strip('-')
    if not base or not _SLUG_RE.match(base):
        base = 'group'
    gid, n = base, 2
    existing = {g.get('id') for g in groups(cfg)}
    while gid in existing:
        gid = f'{base}-{n}'
        n += 1
    return gid


#: 用户可能粘贴的各种写法：owner/name、https 链接、git@ 链接，带不带 .git 都行
_REPO_INPUT_RE = re.compile(
    r'^(?:https?://(?:www\.)?github\.com/|git@github\.com:)'
    r'?([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/*$')


def parse_repo_spec(text: str) -> str | None:
    """把用户随手粘贴的仓库地址收敛成 ``owner/name``；识别不了返回 None。

    与其让用户去记「必须填 owner/name」，不如把常见的四种写法都接住 ——
    GitHub 网页上复制的地址一定带 ``https://github.com/`` 前缀和 ``.git`` 后缀。
    """
    s = (text or '').strip()
    if not s:
        return None
    m = _REPO_INPUT_RE.match(s)
    if not m:
        return None
    return f'{m.group(1)}/{m.group(2)}'


def new_group(folder: str | os.PathLike, name: str | None = None) -> dict:
    """按一个本地文件夹构造分组骨架（校验与落库由调用方负责）。"""
    p = Path(folder)
    label = name or p.name
    return {
        'id': '',
        'name': label,
        'folder': str(p),
        'repo': '',
        'branch': DEFAULTS['branch'],
        'files': [],
        'site': True,
        'site_title': label,
        'docs_dir': DEFAULTS['docs_dir'],
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }


# ───────────────────────────── 校验 ─────────────────────────────

def validate_group(group: dict, cfg: dict | None = None) -> list[str]:
    """校验一个分组，返回问题描述列表；空列表表示通过。"""
    errs: list[str] = []

    gid = group.get('id')
    if not gid:
        errs.append('id 不能为空（小写字母/数字/连字符，如 java-notes）')
    elif not _SLUG_RE.match(str(gid)):
        errs.append(f'id 只能用小写字母、数字、连字符：{gid}')

    folder = group.get('folder')
    if not folder:
        errs.append('folder 不能为空')
    else:
        fp = Path(str(folder))
        if not fp.is_absolute():
            errs.append(f'folder 必须是绝对路径：{folder}')
        elif not fp.is_dir():
            errs.append(f'folder 不存在或不是文件夹：{folder}')

    repo = group.get('repo')
    if not repo:
        errs.append('repo 不能为空（格式 owner/name）')
    elif not _REPO_RE.match(str(repo)):
        errs.append(f'repo 格式应为 owner/name：{repo}')

    branch = str(group.get('branch') or '')
    if not branch:
        errs.append('branch 不能为空')
    elif not _BRANCH_RE.match(branch):
        errs.append(f'branch 含非法字符：{branch}')

    for name in managed_names(group):
        bad = next((c for c in _BAD_NAME_CHARS if c in name), None)
        if bad:
            errs.append(f'文件名不能包含路径分隔符或 ..：{name}')
            continue
        if Path(name).suffix.lower() not in NOTE_EXTENSIONS:
            errs.append(f'只能纳入 {"、".join(NOTE_EXTENSIONS)} 文件：{name}')

    if cfg is not None:
        for other in groups(cfg):
            if other is group or other.get('id') == gid:
                continue
            if folder and _norm(other.get('folder') or '') == _norm(str(folder)):
                errs.append(f'该文件夹已属于分组「{other.get("name")}」'
                            f'（id={other.get("id")}），一个文件夹只能绑一个仓库')
            if repo and str(other.get('repo')) == str(repo):
                errs.append(f'该仓库已被分组「{other.get("name")}」使用 —— '
                            f'两个分组合用同一仓库会互相覆盖')

    return errs


# ───────────────────────────── 工作区 ─────────────────────────────

def workspace_dir(group: dict) -> Path:
    """推送用的本地工作区：``~/.pushnote/workspaces/<id>/``。

    **不在用户的笔记文件夹里**，理由见模块开头。
    """
    return WORKSPACES_DIR / str(group.get('id'))


def docs_path(group: dict) -> Path:
    """站点输出目录（工作区内）。"""
    return workspace_dir(group) / str(group.get('docs_dir') or DEFAULTS['docs_dir'])


def default_commit_message(group: dict, names: list[str] | None = None,
                           cfg: dict | None = None) -> str:
    """生成默认提交信息。

    界面上会把这个字符串填进输入框让用户改（设计稿 S-01），
    这里只是「用户不改也能推」的兜底。
    """
    picked = list(names if names is not None else managed_names(group))
    if len(picked) == 1:
        target = Path(picked[0]).stem
    else:
        target = f'{len(picked)} 个文件'
    tpl = str(defaults_of(cfg or {}).get('commit_template') or '更新 {target}')
    return tpl.format(target=target, group=group.get('name', ''))
