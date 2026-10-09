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
    # 中文文件名默认会被 git 转义成 "\346\226\207..." 这种八进制形式，
    # 任何解析 git 输出的地方（变更清单、状态判断）都会跟着出错。
    git(p, 'config', 'core.quotepath', 'false')
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


# ---------------------------------------------------------------- 凭据

#: 令牌通过**环境变量**传给 git，绝不进命令行 ——
#: 命令行参数在进程列表里是明文可见的，等于把令牌挂在任务管理器上。
TOKEN_ENV_VAR = 'FREEPUSH_GIT_TOKEN'
TOKEN_USERNAME = 'x-access-token'
GH_HELPER = '!gh auth git-credential'


def token_helper() -> str:
    """从环境变量读令牌的 git 凭据助手（shell 形式）。

    git 的 ``!`` 助手是交给 ``sh`` 执行的，所以这里写 shell 语法。
    Git for Windows 自带 sh，三个平台都能跑，不需要额外依赖。
    """
    return (f'!f() {{ echo "username={TOKEN_USERNAME}"; '
            f'echo "password=${TOKEN_ENV_VAR}"; }}; f')


def credential_args(token: str | None) -> list[str]:
    """构造 git 的 ``-c`` 参数：先清掉继承来的助手，再挂上自己的。

    ``-c credential.helper=``（空值）**不能省**：本机全局配置指向
    git-credential-manager，而它并没有 github.com 的凭据 —— 于是会尝试弹交互窗口，
    在非交互环境下表现为**静默挂死**（超时且 stdout/stderr 全空，极具误导性）。

    ``token=None`` 时回落到本机的 ``gh`` 凭据，**仅供开发期调试**：
    别人机器上没装 gh 就用不了，正式链路一律走令牌。
    """
    args = ['-c', 'credential.helper=']
    if token is None:
        return args + ['-c', f'credential.helper={GH_HELPER}']
    return args + ['-c', f'credential.helper={token_helper()}']


def identity_for_account(login: str, uid: int | None = None) -> tuple[str, str]:
    """GitHub 账号 → git 提交身份。

    用 GitHub 的 noreply 邮箱规则，提交才能正确归属到这个账号，
    同时**不把真实邮箱写进仓库历史**。
    """
    email = (f'{uid}+{login}@users.noreply.github.com' if uid
             else f'{login}@users.noreply.github.com')
    return login, email


def ensure_identity_for_account(path: str | Path, login: str, uid: int | None = None,
                                on_log=None) -> tuple[str, str]:
    """把提交身份写进**该仓库的局部配置**，不动用户的全局 git 配置。"""
    log = on_log or (lambda *_a, **_k: None)
    name, email = identity_for_account(login, uid)
    git(path, 'config', 'user.name', name)
    git(path, 'config', 'user.email', email)
    log(f'提交身份：{name} <{email}>')
    return name, email


def short_hash(path: str | Path) -> str:
    return stdout_of(git(path, 'rev-parse', '--short', 'HEAD', check=False))


def staged_numstat(path: str | Path) -> list[dict]:
    """已暂存改动的逐文件增删行数（``git diff --cached --numstat``）。

    给「Push 前先让用户看清这次会推什么」用（设计稿 S-01 的 ``+23 −8``）。
    调用前需要先 ``add_all``。

    非文本文件 git 会给 ``-``，这时按 0 处理 —— 界面显示 ``+0 −0`` 比显示 ``+-`` 好读。
    """
    r = git(path, '-c', 'core.quotepath=false', 'diff', '--cached', '--numstat',
            check=False)
    out: list[dict] = []
    for line in stdout_of(r).splitlines():
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        added, removed, name = parts[0], parts[1], parts[2]
        out.append({
            'path': name,
            'name': Path(name).name,
            'added': int(added) if added.isdigit() else 0,
            'removed': int(removed) if removed.isdigit() else 0,
        })
    return out


def has_staged_changes(path: str | Path) -> bool:
    """暂存区里是否有内容（``git diff --cached --quiet`` 为 1 时有）。"""
    r = git(path, 'diff', '--cached', '--quiet', check=False)
    return r.returncode == 1


def unstage(path: str | Path, paths: list[str]) -> None:
    """把若干文件移出暂存区，**内容仍留在工作区**。

    用于「只推选中的文件」：用户在设计稿 S-01 的清单里取消勾选某项时，
    我们只是不提交它的改动 —— 它仍然躺在工作区里，等下一次推送再带上。
    注意这时候**不能**去清空工作区重建，那样会把该文件从仓库里删掉。

    空仓库（尚无 HEAD）时 ``git reset HEAD`` 不可用，改用 ``git rm --cached``。
    """
    if not paths:
        return
    if head_exists(path):
        git(path, 'reset', '-q', 'HEAD', '--', *paths, check=False)
    else:
        git(path, 'rm', '--cached', '-q', '--', *paths, check=False)


#: 用 ASCII 单元分隔符连接字段 —— 提交信息里可能有 ``|`` ``:`` 这类常见分隔符
_LOG_SEP = '%x1f'


def recent_commits(path: str | Path, limit: int = 5) -> list[dict]:
    """最近的提交记录（新到旧）：``[{'hash','message','ts'}, ...]``。

    侧栏「最近推送」列表直接用这个 —— 读真实历史，不编造。
    """
    r = git(path, 'log', f'-{limit}',
            f'--format=%h{_LOG_SEP}%s{_LOG_SEP}%ct', check=False)
    out: list[dict] = []
    for line in stdout_of(r).splitlines():
        parts = line.split('\x1f')
        if len(parts) < 3:
            continue
        try:
            ts = int(parts[2])
        except ValueError:
            ts = 0
        out.append({'hash': parts[0], 'message': parts[1], 'ts': ts})
    return out


# ---------------------------------------------------------------- 提交 / 推送

def add_all(path: str | Path) -> None:
    git(path, 'add', '-A')


def commit(path: str | Path, message: str) -> None:
    git(path, 'commit', '-m', message)


def push(path: str | Path, *, token: str | None = None,
         retries: int = 3, interval: int = 5, on_log=None,
         set_upstream: bool = True) -> tuple[bool, int]:
    """推送 HEAD 到 origin，失败自动重试。

    ``token`` 给定即用绑定的 OAuth 令牌（正式链路）。
    返回 ``(是否成功, 实际尝试次数)``。**不抛异常也不 sys.exit** ——
    失败信息要交回调用方，由界面按错误种类给不同的提示。
    """
    log = on_log or (lambda *_a, **_k: None)
    if not remote_url(path):
        log('!! 尚未配置远程仓库 origin，已跳过推送。')
        return False, 0

    cmd = ['git', *credential_args(token), 'push']
    cmd += (['-u'] if set_upstream else []) + ['origin', 'HEAD']

    env = envprobe.clean_env()
    if token:
        env[TOKEN_ENV_VAR] = token

    last_detail = ''
    for attempt in range(1, retries + 1):
        log(f'推送中…（第 {attempt}/{retries} 次）')
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
    log('     3) 授权失效 —— 在设置里重新授权 GitHub 账号。')
    log('     4) 远端有新提交（例如你曾在网页上编辑）—— 需要先拉取。')
    return False, retries
