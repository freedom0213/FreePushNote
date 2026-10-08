# -*- coding: utf-8 -*-
"""git 调用封装：统一 UTF-8、净化环境、gh 凭据、失败重试。

★ 凭据那条命令是从 ``java-notes/tools/sync.py`` 原样搬过来的，改动前请先读理由：

  本机全局 ``credential.helper`` 指向 PortableGit 自带的 git-credential-manager.exe，
  但从未为 github.com 存过凭据。GCM 在非交互环境下会尝试弹交互窗口 → 表现为
  **静默挂死**（超时且 stdout/stderr 全空，极具误导性）。
  因此先用 ``-c credential.helper=`` 清掉继承来的助手，再挂上
  ``!gh auth git-credential``（本机 gh CLI 已认证，可直接提供凭据）。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import envprobe

DEFAULT_TIMEOUT = 180
PUSH_TIMEOUT = 300


class GitError(RuntimeError):
    """git 命令执行失败。"""


def _decode(raw: bytes | None) -> str:
    if not raw:
        return ''
    return raw.decode('utf-8', errors='replace')


def _run(args: list[str], cwd: str | Path, *, env: dict | None = None,
         timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """执行命令并以 UTF-8 解码输出。

    文本模式下 ``subprocess`` 会按 locale（Windows 中文环境为 GBK）解码，
    中文路径/文件名极易乱码，所以一律用 bytes 收、自己按 UTF-8 解。
    """
    return subprocess.run(
        list(args), cwd=str(cwd), capture_output=True,
        env=env if env is not None else envprobe.clean_env(),
        timeout=timeout,
    )


def git(repo_dir: str | Path, *args: str, check: bool = True,
        env: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """调用 git 子命令。``check=True`` 时非零退出码抛 :class:`GitError`。"""
    proc = _run(['git', *args], repo_dir, env=env, timeout=timeout)
    if check and proc.returncode != 0:
        detail = (_decode(proc.stderr) or _decode(proc.stdout)).strip()
        raise GitError(f'git {" ".join(args)} 失败（退出码 {proc.returncode}）：{detail}')
    return proc


def stdout_of(proc: subprocess.CompletedProcess) -> str:
    return _decode(proc.stdout).strip()


# ---------------------------------------------------------------- 探测

def is_repo(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_dir():
        return False
    try:
        r = git(p, 'rev-parse', '--is-inside-work-tree', check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and stdout_of(r) == 'true'


def head_exists(path: str | Path) -> bool:
    """仓库是否已有提交（空仓库返回 False）。"""
    r = git(path, 'rev-parse', '--verify', 'HEAD', check=False)
    return r.returncode == 0


def has_changes(path: str | Path) -> bool:
    """是否存在未提交改动（含未跟踪文件）。"""
    r = git(path, 'status', '--porcelain', check=False)
    return bool(stdout_of(r))


def current_branch(path: str | Path) -> str:
    r = git(path, 'rev-parse', '--abbrev-ref', 'HEAD', check=False)
    name = stdout_of(r)
    return name if name and name != 'HEAD' else ''


def remote_url(path: str | Path, name: str = 'origin') -> str:
    r = git(path, 'remote', 'get-url', name, check=False)
    return stdout_of(r)


# ---------------------------------------------------------------- 准备

def init_repo(path: str | Path, branch: str = 'main', on_log=None) -> None:
    log = on_log or (lambda *_a, **_k: None)
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    log(f'初始化本地仓库：{p}')
    git(p, 'init', '-b', branch)
    ensure_lf_attributes(p, on_log=on_log)


def ensure_identity(path: str | Path, on_log=None) -> None:
    """确保该仓库有可用的提交身份；缺失时从全局继承，全局也缺失才提示。"""
    log = on_log or (lambda *_a, **_k: None)
    name = stdout_of(git(path, 'config', 'user.name', check=False))
    email = stdout_of(git(path, 'config', 'user.email', check=False))
    if not name or not email:
        log('!! 未检测到 git 提交身份（user.name / user.email）')
        log('   请先执行：git config --global user.name "你的名字"')
        log('           git config --global user.email "你的邮箱"')


def ensure_lf_attributes(path: str | Path, on_log=None) -> None:
    """写入 .gitattributes（eol=lf），避免 Windows 每次提交都冒 CRLF 警告。"""
    log = on_log or (lambda *_a, **_k: None)
    f = Path(path) / '.gitattributes'
    if f.exists():
        return
    f.write_text('* text=auto eol=lf\n', encoding='utf-8', newline='\n')
    log('已生成 .gitattributes（统一 LF）')


def ensure_remote(path: str | Path, repo: str, on_log=None) -> str:
    """保证 origin 指向 https://github.com/<repo>.git，返回该 URL。"""
    log = on_log or (lambda *_a, **_k: None)
    url = f'https://github.com/{repo}.git'
    existing = remote_url(path)
    if not existing:
        log(f'添加远程仓库 origin -> {url}')
        git(path, 'remote', 'add', 'origin', url)
    elif existing != url:
        log(f'更新远程仓库 origin：{existing} -> {url}')
        git(path, 'remote', 'set-url', 'origin', url)
    return url


# ---------------------------------------------------------------- 提交 / 推送

def add_all(path: str | Path) -> None:
    git(path, 'add', '-A')


def commit(path: str | Path, message: str) -> None:
    git(path, 'commit', '-m', message)


def push(path: str | Path, *, helper: str = '!gh auth git-credential',
         retries: int = 3, interval: int = 5, on_log=None,
         set_upstream: bool = False) -> tuple[bool, int]:
    """推送 HEAD 到 origin，失败自动重试。

    返回 ``(是否成功, 实际尝试次数)``。**不做 sys.exit**，失败信息交回调用方展示。
    """
    log = on_log or (lambda *_a, **_k: None)
    if not remote_url(path):
        log('!! 尚未配置远程仓库 origin，已跳过推送。')
        return False, 0

    cmd = ['git', '-c', 'credential.helper=',
           f'-c', f'credential.helper={helper}', 'push']
    cmd += (['-u'] if set_upstream else []) + ['origin', 'HEAD']

    env = envprobe.clean_env()
    last_detail = ''
    for attempt in range(1, retries + 1):
        log(f'$ {" ".join(cmd)}    (第 {attempt}/{retries} 次)')
        try:
            proc = _run(cmd, path, env=env, timeout=PUSH_TIMEOUT)
        except subprocess.TimeoutExpired:
            last_detail = f'超时（>{PUSH_TIMEOUT}s）'
            log(f'！！推送超时（{PUSH_TIMEOUT}s）')
            proc = None

        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                text = _decode(stream)
                if text.strip():
                    log(text.rstrip())
            if proc.returncode == 0:
                return True, attempt
            last_detail = (_decode(proc.stderr) or _decode(proc.stdout)).strip()

        if attempt < retries:
            log(f'推送失败，{interval} 秒后自动重试…')
            time.sleep(interval)

    log('')
    log(f'！！推送连续 {retries} 次失败。最后一次错误：{last_detail or "（无输出）"}')
    log('   你的改动已经提交到本地仓库，不会丢失。')
    log('   常见原因：')
    log('     1) 网络 / 代理抖动 —— 过一会儿再点一次「Push」，会自动补上。')
    log('     2) 代理软件没开 —— git 若配了 http.proxy，确认它在运行。')
    log('     3) 远端有新提交 —— 需要先拉取合并（本工具暂不自动合并）。')
    return False, retries
