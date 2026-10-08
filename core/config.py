# -*- coding: utf-8 -*-
"""配置读写：绑定「某个笔记 txt 文件 → 某个 GitHub 仓库」。

设计要点
--------
* 配置放在用户目录（默认 ``~/.pushnote/config.json``），**不在任何 git 仓库内**，
  因此不可能被误提交。
* 写入采用「临时文件 + ``os.replace``」的原子方式，避免断电 / 中断产生半截文件。
* 校验尽量严格：路径必须是绝对路径、必须存在、必须是 .txt —— 宁可提前报错，
  也不要出现「以为同步了、其实没更新」。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# 允许用环境变量 PUSHNOTE_HOME 重定向，便于测试和多套配置共存
_CONFIG_HOME = os.environ.get('PUSHNOTE_HOME')
CONFIG_DIR = Path(_CONFIG_HOME) if _CONFIG_HOME else (Path.home() / '.pushnote')
CONFIG_PATH = CONFIG_DIR / 'config.json'
REPOS_DIR = CONFIG_DIR / 'repos'

VERSION = 1
VALID_MODES = ('auto', 'site', 'raw')

# owner/name：GitHub 用户名与仓库名允许字母数字 . _ -
_REPO_RE = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
# binding id：小写字母 / 数字 / 连字符，且以字母数字开头
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')

DEFAULTS: dict = {
    'commit_template': 'chore: 更新笔记 {ts}',
    'retry': 3,
    'retry_interval': 5,
    'credential_helper': '!gh auth git-credential',
    'branch': 'main',
}


class ConfigError(ValueError):
    """配置非法（格式错误、路径不存在等）。"""


def blank_config() -> dict:
    return {'version': VERSION, 'defaults': dict(DEFAULTS), 'bindings': [], 'active_id': None}


def defaults_of(cfg: dict) -> dict:
    """把全局默认值与配置里的覆盖项合并。"""
    merged = dict(DEFAULTS)
    merged.update(cfg.get('defaults') or {})
    return merged


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
    cfg.update(raw)
    cfg['bindings'] = [b for b in (cfg.get('bindings') or []) if isinstance(b, dict)]
    return cfg


def save(cfg: dict, path: Path | str | None = None) -> Path:
    """原子写入配置，返回落盘路径。"""
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    text = json.dumps(cfg, ensure_ascii=False, indent=2) + '\n'
    tmp.write_text(text, encoding='utf-8', newline='\n')
    os.replace(tmp, p)  # 同一分区上的原子替换
    return p


def validate_binding(binding: dict, cfg: dict | None = None) -> list[str]:
    """校验单条绑定，返回问题描述列表；空列表表示通过。"""
    errs: list[str] = []

    bid = binding.get('id')
    if not bid:
        errs.append('id 不能为空（小写字母/数字/连字符，如 java-bagu）')
    elif not _SLUG_RE.match(str(bid)):
        errs.append(f'id 只能用小写字母、数字、连字符：{bid}')

    note = binding.get('note_path')
    if not note:
        errs.append('note_path 不能为空')
    else:
        np = Path(str(note))
        if not np.is_absolute():
            errs.append(f'note_path 必须是绝对路径：{note}')
        elif np.suffix.lower() != '.txt':
            errs.append(f'note_path 必须是 .txt 文件：{note}')
        elif not np.exists():
            errs.append(f'note_path 指向的文件不存在：{note}')

    repo = binding.get('repo')
    if not repo:
        errs.append('repo 不能为空（格式 owner/name）')
    elif not _REPO_RE.match(str(repo)):
        errs.append(f'repo 格式应为 owner/name：{repo}')

    mode = binding.get('mode', 'auto')
    if mode not in VALID_MODES:
        errs.append(f'mode 必须是 {"/".join(VALID_MODES)} 之一，当前为 {mode}')

    wd = binding.get('workdir')
    if wd is not None and not Path(str(wd)).is_absolute():
        errs.append(f'workdir 若填写必须是绝对路径：{wd}')

    if cfg is not None:
        same = [b for b in cfg.get('bindings', []) if b.get('id') == bid]
        if len(same) > 1:
            errs.append(f'id 重复：{bid}')

    return errs


def get_binding(cfg: dict, bid: str | None) -> dict | None:
    if not bid:
        return None
    for b in cfg.get('bindings', []):
        if b.get('id') == bid:
            return b
    return None


def active_binding(cfg: dict) -> dict | None:
    """当前选中的绑定；没有指定时退回第一条。"""
    b = get_binding(cfg, cfg.get('active_id'))
    if b is not None:
        return b
    bindings = cfg.get('bindings') or []
    return bindings[0] if bindings else None


def upsert_binding(cfg: dict, binding: dict) -> dict:
    """按 id 新增或覆盖一条绑定。"""
    bindings = cfg.setdefault('bindings', [])
    for i, b in enumerate(bindings):
        if b.get('id') == binding.get('id'):
            bindings[i] = binding
            break
    else:
        bindings.append(binding)
    if not cfg.get('active_id'):
        cfg['active_id'] = binding.get('id')
    return cfg


def remove_binding(cfg: dict, bid: str) -> dict:
    cfg['bindings'] = [b for b in cfg.get('bindings', []) if b.get('id') != bid]
    if cfg.get('active_id') == bid:
        rest = cfg.get('bindings') or []
        cfg['active_id'] = rest[0]['id'] if rest else None
    return cfg


def workdir_for(binding: dict) -> Path:
    """绑定的本地 git 工作区。

    显式填了 ``workdir`` 就用它（例如直接复用现成的 java-notes 目录）；
    否则落在 ``~/.pushnote/repos/<id>/``。
    """
    wd = binding.get('workdir')
    if wd:
        return Path(str(wd))
    return REPOS_DIR / str(binding.get('id'))
