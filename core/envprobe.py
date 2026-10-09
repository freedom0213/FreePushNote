# -*- coding: utf-8 -*-
"""子进程环境净化 + 代理探测。

这里的两条规则都是实测踩出来的，改动前请先读理由：

1. **环境变量里的 ``http_proxy`` / ``https_proxy`` 必须剔除。**
   本机该变量指向沙箱代理，它不支持 HTTPS CONNECT 隧道，会让 ``git`` / ``gh``
   的请求**静默挂死、零输出**（表现为超时且 stdout/stderr 全空，极具误导性）。

2. **``gh`` 需要显式注入代理。**
   ``gh``（Go 编写）**不读 git 的配置**，只认环境变量 ``HTTP_PROXY`` / ``HTTPS_PROXY``；
   而 git 自己的 ``http.proxy``（用户自己的代理软件，形式如 127.0.0.1:<port>）是另一套、
   且是可用的。所以要把 git 的 http.proxy 取出来，显式塞给子进程环境。
"""
from __future__ import annotations

import os
import subprocess

_PROXY_KEYS = frozenset(('http_proxy', 'https_proxy', 'all_proxy', 'ftp_proxy', 'no_proxy'))

#: Windows 上 CREATE_NO_WINDOW 的取值。直接写常量是为了不依赖平台常量是否存在。
_CREATE_NO_WINDOW = 0x08000000


def no_window_kwargs() -> dict:
    """让子进程**不弹控制台窗口**（Windows 专用，其它平台返回空字典）。

    不加这个，每一次 ``git`` 调用都会在屏幕上闪一个黑色控制台窗口。
    用户看到的是「一操作就冒出一堆 cmd 窗口」—— 既打断视线，
    也把「其实是在调 git」这个实现细节摆到了台面上。

    ``CREATE_NO_WINDOW`` 只影响窗口创建，**不影响** stdout/stderr 的捕获，
    所以错误信息照样拿得到。

    返回的字典直接展开进 ``subprocess.run(...)`` 即可。
    """
    if os.name == 'nt':
        return {'creationflags': _CREATE_NO_WINDOW}
    return {}


def git_http_proxy(cwd: str | os.PathLike | None = None) -> str:
    """读取本机 git 配置中的 ``http.proxy``；未配置或执行失败时返回空串。"""
    try:
        r = subprocess.run(
            ['git', 'config', '--get', 'http.proxy'],
            cwd=cwd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10,
            **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def clean_env(base: dict | None = None, proxy: str | None = None) -> dict:
    """返回一份干净的子进程环境。

    * 剔除所有 ``*_proxy`` 变量（见模块开头第 1 条）。
    * 把 git 的 ``http.proxy`` 注入为 ``HTTP_PROXY`` / ``HTTPS_PROXY``（第 2 条）。

    ``proxy`` 显式传空串 ``''`` 表示「不要代理」。
    """
    env = dict(base if base is not None else os.environ)
    for key in list(env):
        if key.lower() in _PROXY_KEYS:
            env.pop(key, None)
    if proxy is None:
        proxy = git_http_proxy()
    if proxy:
        env['HTTP_PROXY'] = proxy
        env['HTTPS_PROXY'] = proxy
    return env
