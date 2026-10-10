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
FETCH_TIMEOUT = 180


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
        # 不让它弹控制台窗口：否则每调一次 git 就闪一个黑框，
        # 用户看到的就是「一点击冒出一堆 cmd」，既打断视线又暴露了实现
        **envprobe.no_window_kwargs(),
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


def resolved_remote_url(path: str | Path, name: str = 'origin',
                        env: dict | None = None) -> str:
    """``git`` **实际会访问**的地址（已应用 ``url.*.insteadOf`` 改写）。

    :func:`remote_url` 读的是配置里的原值；这个读的是生效值。
    两者的差别恰恰是要命的地方：配置写着 ``https://``，实际走 ``git@``（SSH）
    —— 那种情况下令牌根本用不上，认证悄悄换成了本机的 SSH 密钥。
    比直接失败更危险，因为「换了身份」在界面上看不出来。
    """
    r = git(path, 'ls-remote', '--get-url', name, check=False, env=env)
    return stdout_of(r)


def push_env(token: str | None = None) -> dict:
    """推送子进程的环境。

    除 :mod:`envprobe` 那两条净化规则（剔除不可用的 ``*_proxy``、
    把 git 的 ``http.proxy`` 注入为 ``HTTP_PROXY``）之外，多一条：

    **``GIT_CONFIG_NOSYSTEM=1``** —— 让这个子进程无视系统级 gitconfig。
    理由很具体：本机 ``D:\\skywaimai\\Git`` 的系统级配置里有
    ``[url "git@github.com:"] insteadOf = https://github.com/`` 和
    ``core.sshCommand = ... -p 443 ssh.github.com``，一句 ``git push``
    会被整段改写成 SSH 直连，令牌形同废纸。实测那种连接在本机是被重置的
    （``Connection reset by 20.205.243.160 port 443``），于是推送永远失败。

    只影响这一个子进程，**不改动任何配置文件**。
    """
    env = envprobe.clean_env()
    env['GIT_CONFIG_NOSYSTEM'] = '1'
    if token:
        env[TOKEN_ENV_VAR] = token
    return env


def looks_like_ssh(url: str) -> bool:
    """这个远程地址是不是走 SSH。

    只认两种真正会让「令牌失效」的形式：``ssh://...``，
    以及 scp 形式的 ``user@host:path``（``git@github.com:owner/repo.git``）。

    **本机路径不算** —— 自测拿本地裸仓库当远端，那些地址长成
    ``C:/.../bare`` 或 ``/tmp/.../bare``，不能因为「不是 https」就被拦下。
    """
    if url.startswith('ssh://'):
        return True
    _scheme, sep, _rest = url.partition('://')
    if sep:                       # 有明确 scheme：不是 ssh 就交给它自己的协议
        return False
    head = url.split(':', 1)[0]
    return ':' in url and '@' in head


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

    env = push_env(token)

    # 令牌只能通过 https 用。若本机 git 把地址改写成 SSH，认证会**悄悄换成**
    # 本机的 SSH 密钥 —— 推上去的东西署着另一个身份，界面上还显示成功。
    # 与其让它发生，不如在这儿停下来说清原因。
    target = resolved_remote_url(path, env=env)
    if looks_like_ssh(target):
        log(f'！！推送地址是 SSH 形式，已中止：{target}')
        log('   本机 git 的 url.*.insteadOf 规则把 GitHub 地址改写成了 SSH，')
        log('   这样令牌用不上，认证会改走本机 SSH 密钥。')
        log('   排查：git config --show-origin --get-regexp "url\\..*insteadof"')
        return False, 0

    cmd = ['git', *credential_args(token), 'push']
    cmd += (['-u'] if set_upstream else []) + ['origin', 'HEAD']

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


# ---------------------------------------------------------------- 拉取 / 比对
#
# 下面这一组是 Pull 与「推送前远端检测」的地基。它们的共同点：
# **全部只读或只动工作区仓库，绝不触碰用户的笔记文件夹** ——
# 写回那一步在 core.pipeline 里显式完成，便于审计。


def fetch(path: str | Path, branch: str, *, token: str | None = None,
          retries: int = 2, interval: int = 4, on_log=None) -> bool:
    """把远端分支取回本地引用（``refs/remotes/origin/<branch>``），**不动工作树**。

    环境与 :func:`push` 完全一致：``GIT_CONFIG_NOSYSTEM=1`` 防止本机系统级
    gitconfig 把 https 地址改写成 SSH（那样令牌用不上，认证会悄悄换成本机
    密钥），令牌经环境变量交给凭据助手，不进命令行。
    """
    log = on_log or (lambda *_a, **_k: None)
    if not remote_url(path):
        log('!! 尚未配置远程仓库 origin，已跳过拉取。')
        return False

    env = push_env(token)
    cmd = ['git', *credential_args(token), 'fetch', '--prune', 'origin', branch]

    for attempt in range(1, max(retries, 1) + 1):
        log(f'读取远端（第 {attempt}/{max(retries, 1)} 次）…')
        try:
            proc = _run(cmd, path, env=env, timeout=FETCH_TIMEOUT)
        except subprocess.TimeoutExpired:
            log(f'！！读取远端超时（{FETCH_TIMEOUT}s）')
            proc = None

        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                text = _decode(stream)
                if text.strip():
                    log(text.rstrip())
            if proc.returncode == 0:
                return True

        if attempt < max(retries, 1):
            log(f'读取远端失败，{interval} 秒后重试…')
            time.sleep(interval)

    log('！！读取远端失败（网络或授权问题）。')
    return False


def rev_exists(path: str | Path, rev: str) -> bool:
    """某个修订（分支名 / sha / ``HEAD``）在本地是否解析得出来。"""
    proc = git(path, 'rev-parse', '--verify', '--quiet', rev, check=False)
    return proc.returncode == 0


def count_commits(path: str | Path, rev: str) -> int:
    text = stdout_of(git(path, 'rev-list', '--count', rev, check=False))
    return int(text) if text.isdigit() else 0


def ahead_behind(path: str | Path, branch: str,
                 remote: str = 'origin') -> tuple[int, int]:
    """返回 ``(本地领先, 本地落后)`` 的提交数。

    三种情形分别处理，因为它们的含义完全不同：

    * 远端还没有这个分支 → ``(0, 0)``：没什么可拉的
    * 本地还没提交过（比如新电脑第一次拉）→ ``(0, 远端提交数)``：
      这时 ``rev-list HEAD...origin/x`` 会直接报错，不能当成「已一致」
    * 正常情形 → 走 ``rev-list --left-right --count``
    """
    ref = f'{remote}/{branch}'
    if not rev_exists(path, ref):
        return (0, 0)
    if not head_exists(path):
        return (0, count_commits(path, ref))

    proc = git(path, 'rev-list', '--left-right', '--count',
               f'HEAD...{ref}', check=False)
    if proc.returncode != 0:
        return (0, 0)
    parts = stdout_of(proc).split()
    if len(parts) != 2:
        return (0, 0)
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return (0, 0)


def merge_base(path: str | Path, a: str, b: str) -> str:
    """两个修订的共同祖先。**分叉时三方合并的 ``base`` 必须用它，不能用 HEAD**。"""
    return stdout_of(git(path, 'merge-base', a, b, check=False))


def diff_names(path: str | Path, rev_range: str) -> list[str]:
    """某个提交区间（如 ``HEAD..origin/main``）里改动过的文件路径。

    用来回答一个 Pull 绕不开的问题：**远端这次到底改了什么** ——
    如果改的全是自动生成的站点文件，那本地笔记原文根本不需要同步，
    但用户必须被告知，否则他会以为「Pull 成功了，仓库里的改动应该已经生效」。
    """
    proc = git(path, '-c', 'core.quotepath=false',
               'diff', '--name-only', rev_range, check=False)
    if proc.returncode != 0:
        return []
    return [l for l in stdout_of(proc).splitlines() if l.strip()]


def show_file(path: str | Path, rev: str, rel: str) -> str | None:
    """从对象库取某个文件在某次提交里的内容；该修订里没有这个文件则返回 ``None``。

    一定要从**对象库**取（``git show``），不要读工作树 ——
    工作树每次推送前都会被清空重建，只有刚复制完那一刻才等于本地笔记。
    """
    proc = git(path, '-c', 'core.quotepath=false', 'show', f'{rev}:{rel}', check=False)
    if proc.returncode != 0:
        return None
    return (proc.stdout or b'').decode('utf-8', errors='replace')


def merge_file(base_text: str, ours_text: str, theirs_text: str) -> tuple[str, int]:
    """三方合并。返回 ``(合并结果, 冲突块数)``；冲突块数 > 0 表示需要人来拍板。

    用 ``git merge-file``：只有**两边改到同一处**才报冲突，各改各的会自动合掉。
    文本一律按 UTF-8 落临时文件（内容此时已经是归一化过的 UTF-8/LF）。
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix='pushnote_merge_') as td:
        d = Path(td)
        (d / 'base').write_text(base_text, encoding='utf-8', newline='\n')
        (d / 'ours').write_text(ours_text, encoding='utf-8', newline='\n')
        (d / 'theirs').write_text(theirs_text, encoding='utf-8', newline='\n')

        proc = _run(['git', 'merge-file', '-p', '--diff3',
                     str(d / 'ours'), str(d / 'base'), str(d / 'theirs')], d)
        merged = (proc.stdout or b'').decode('utf-8', errors='replace')
        if proc.returncode < 0:
            raise GitError(f'三方合并失败（退出码 {proc.returncode}）')
        return merged, proc.returncode


def reset_hard(path: str | Path, rev: str) -> None:
    """把工作区分支硬指向 ``rev``。

    用它的唯一场合：Pull 结束后让中转区追平远端，使下一次推送是快进。
    中转区的工作树是**临时镜像**（每次推送前都整块重建），所以丢弃它安全；
    用户的笔记文件不受影响。
    """
    git(path, 'reset', '--hard', rev)
