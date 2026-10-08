# -*- coding: utf-8 -*-
"""已绑定的 GitHub 账号：状态、令牌访问、持久化。

**账号信息与令牌分开存，是有意为之：**

* 账号公开信息（login / 昵称 / 头像地址）放 ``~/.pushnote/config.json`` 的 ``github`` 段
* 令牌单独走 :mod:`core.secretstore`（Windows DPAPI 加密）

理由：配置文件常被拷来拷去、也可能被贴进 issue 里问问题；而令牌必须留在本机。
混在一起迟早出事。

**「已绑定」的判定是两件都在**：账号信息存在 **且** 令牌文件存在。
只有一条时（例如用户手动删了凭据目录）按未绑定处理，让界面引导重新授权 ——
半死不活地进入推送然后失败，比直接说「需要重新绑定」要难受得多。
"""
from __future__ import annotations

from dataclasses import dataclass

from core import config as core_config
from core import ghauth, secretstore


@dataclass
class BoundAccount:
    """当前绑定的账号 + 可用令牌。"""

    login: str
    name: str = ''
    avatar_url: str = ''
    token: str = ''
    persisted: bool = True      # 令牌是否已成功落盘（False = 仅本次会话有效）

    @property
    def display(self) -> str:
        return f'{self.name}（{self.login}）' if self.name else self.login


def info() -> dict | None:
    """配置里记录的账号信息（不含令牌）；未绑定返回 None。"""
    try:
        cfg = core_config.load()
    except core_config.ConfigError:
        return None
    gh = cfg.get('github') or {}
    return gh if gh.get('login') else None


def token(login: str) -> str | None:
    """读取某个账号的令牌；不存在返回 None。"""
    try:
        return secretstore.load_token(login)
    except (OSError, ValueError):
        # 凭据文件损坏 —— 当作没有，界面会引导重新授权
        return None


def session() -> BoundAccount | None:
    """当前可用会话（账号信息 + 令牌都在）；否则 None。"""
    gh = info()
    if not gh:
        return None
    tok = token(str(gh['login']))
    if not tok:
        return None
    return BoundAccount(
        login=str(gh['login']),
        name=str(gh.get('name') or ''),
        avatar_url=str(gh.get('avatar_url') or ''),
        token=tok,
    )


def bind(account: ghauth.Account, tok: str) -> BoundAccount:
    """写入账号信息并保存令牌。令牌存不下来时不抛异常，而是标记 ``persisted=False``。

    这样用户这一次仍能用（令牌留在内存里），但界面必须如实告诉他
    「下次启动需要重新授权」—— 而不是假装存好了。
    """
    persisted = True
    try:
        secretstore.save_token(account.login, tok)
    except (OSError, ValueError):
        persisted = False

    try:
        cfg = core_config.load()
    except core_config.ConfigError:
        cfg = core_config.blank_config()
    cfg['github'] = {
        'login': account.login,
        'name': account.name,
        'avatar_url': account.avatar_url,
        'id': account.id,
    }
    try:
        core_config.save(cfg)
    except OSError:
        persisted = False

    return BoundAccount(login=account.login, name=account.name,
                        avatar_url=account.avatar_url, token=tok,
                        persisted=persisted)


def unbind(delete_token: bool = True) -> None:
    """解除绑定：清掉配置里的账号信息，并删除令牌文件。"""
    gh = info()
    if gh and delete_token:
        try:
            secretstore.delete_token(str(gh['login']))
        except (OSError, ValueError):
            pass
    try:
        cfg = core_config.load()
    except core_config.ConfigError:
        return
    cfg.pop('github', None)
    try:
        core_config.save(cfg)
    except OSError:
        pass


def secret_backend() -> tuple[str, str]:
    """返回 ``(后端标识, 给用户看的说明)``，供界面如实显示存储方式。"""
    return secretstore.BACKEND, secretstore.BACKEND_LABEL
