# -*- coding: utf-8 -*-
"""GitHub 账号认证：OAuth Device Flow。

为什么是 Device Flow
--------------------
桌面应用没有可用的回调地址（不能像网页那样跳回来接住 token），
Device Flow 正是为这类场景设计的：

    应用申请设备码 → 拿到给用户看的 8 位用户码
      → 用户去 github.com/login/device 输入
      → 应用按固定间隔轮询，直到用户点完授权、取回 token

它对开源项目还有一个关键好处：**不需要 client secret**。
client_id 只是公开标识（见 DEFAULT_CLIENT_ID 的说明），
所以代码可以放心公开，不存在「密钥泄露」问题。

代理
----
沿用 envprobe.py 的结论：本机环境变量里的 ``*_proxy`` 指向不可用的沙箱代理，
会让请求**静默挂死**，必须剔除；真正可用的是 git 配置里的 ``http.proxy``。
本模块默认走 ``_auto_proxy()``，与子进程侧保持一致。

可测试性
--------
所有网络出口都收在 :class:`Transport` 后面。自测时注入假传输，
就能在不联网的情况下把轮询状态机的每条分支跑一遍
（见 ``tools/auth_selftest.py``）。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import envprobe

# ───────────────────────────── 常量 ─────────────────────────────

DEVICE_CODE_URL = 'https://github.com/login/device/code'
TOKEN_URL = 'https://github.com/login/oauth/access_token'
API_ROOT = 'https://api.github.com'

#: 默认申请的权限。``repo`` 含私有仓库读写（用户可能想把笔记放私有仓库）；
#: 只要公开仓库的话传 ``public_repo``，但默认取宽的那个，避免「推不上去」的困惑。
DEFAULT_SCOPE = 'repo read:user'

#: OAuth App 的 client_id。**它不是密钥**，可以公开——
#: 任何用这个软件的人授权时，GitHub 上显示的都是同一个应用名。
#: 留空表示尚未配置，此时所有认证动作都会报「未配置」而不是静默失败。
#: 也可以通过环境变量 FREEPUSH_GITHUB_CLIENT_ID 或配置项 oauth_client_id 覆盖。
DEFAULT_CLIENT_ID = 'Ov23libaFpw8rEdsDUhh'

CLIENT_ID_ENV = 'FREEPUSH_GITHUB_CLIENT_ID'

#: GitHub 要求每个请求都带 UA，否则直接 403。
USER_AGENT = 'FreePushNote'

#: 轮询间隔下限。协议规定客户端间隔不得低于 5 秒，GitHub 返回的也是 5。
MIN_POLL_INTERVAL = 5

#: 连接超时（秒）。授权轮询本身是长过程，这个超时只管单次请求。
CONNECT_TIMEOUT = 20

# 错误种类：UI 需要按种类给不同文案和按钮，不能共用一句「认证失败」
KIND_CONFIG = 'config'          # 没配 client_id
KIND_NETWORK = 'network'        # 连不上 / 超时 / 代理坏了
KIND_DENIED = 'denied'          # 用户在网页上点了拒绝
KIND_EXPIRED = 'expired'        # 设备码过期，用户没来得及输入
KIND_CANCELLED = 'cancelled'    # 用户自己关掉了对话框
KIND_API = 'api'                # GitHub 明确返回的错误
KIND_PARSE = 'parse'            # 响应不是预期格式（代理劫持的典型症状）


class AuthError(RuntimeError):
    """认证过程中的可预期失败。

    ``kind`` 决定 UI 给什么文案、配什么按钮；``detail`` 放原始报错，
    只在「查看技术详情」里展示。
    """

    def __init__(self, kind: str, message: str, detail: str = '') -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return self.kind in (KIND_NETWORK, KIND_API)


@dataclass(frozen=True)
class DeviceCode:
    """一次授权的「入场券」——给用户看的用户码，和给程序用的设备码。"""

    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    verification_uri_complete: str = ''

    @property
    def expires_minutes(self) -> int:
        return max(1, self.expires_in // 60)


@dataclass(frozen=True)
class Token:
    """换回来的访问令牌。"""

    access_token: str
    scope: str = ''
    token_type: str = 'bearer'
    refresh_token: str = ''
    expires_in: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    def masked(self) -> str:
        """给日志/界面用的脱敏形式，绝不留完整 token。"""
        t = self.access_token
        return f'{t[:4]}…{t[-4:]}' if len(t) > 10 else '…'


@dataclass(frozen=True)
class Account:
    """已授权账号的公开信息（不含 token）。"""

    login: str
    name: str = ''
    avatar_url: str = ''
    id: int = 0

    @property
    def display(self) -> str:
        return f'{self.name}（{self.login}）' if self.name else self.login


# ───────────────────────────── 网络出口 ─────────────────────────────

class Transport(Protocol):
    """网络出口协议。自测时换成假实现即可完全离线。"""

    def post_form(self, url: str, fields: dict) -> tuple[int, dict]:
        ...

    def get_json(self, url: str, token: str) -> tuple[int, dict]:
        ...


def _auto_proxy() -> str:
    """本机该走哪个代理：git 配置里的 http.proxy（与 envprobe 同源）。"""
    return envprobe.git_http_proxy()


def build_opener(proxy: str | None = None) -> urllib.request.OpenerDirector:
    """按需构造 urllib opener。

    * ``proxy is None`` —— 自动：取 git 的 ``http.proxy``（可能为空 → 直连）
    * ``proxy == ''``   —— 明确不走代理
    * 其它字符串        —— 显式指定，如 ``http://127.0.0.1:65532``
    """
    if proxy is None:
        proxy = _auto_proxy()
    if not proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))


class UrllibTransport:
    """基于标准库的实现——不引第三方依赖，打包体积不受影响。"""

    def __init__(self, proxy: str | None = None, timeout: int = CONNECT_TIMEOUT) -> None:
        self._opener = build_opener(proxy)
        self._timeout = timeout

    # -- 内部 ------------------------------------------------------

    def _open(self, req: urllib.request.Request) -> tuple[int, bytes]:
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return int(resp.status), resp.read()
        except urllib.error.HTTPError as exc:
            # GitHub 的 OAuth 端点出错时也返回 200 + {"error": ...}，
            # 但 API 端点会用 4xx，所以两者都要把 body 留下来。
            try:
                return int(exc.code), exc.read()
            except Exception:  # noqa: BLE001
                return int(exc.code), b''
        except urllib.error.URLError as exc:
            raise AuthError(KIND_NETWORK,
                            '连不上 GitHub，请检查网络或代理设置。',
                            f'{type(exc.reason).__name__}: {exc.reason}') from exc
        except TimeoutError as exc:
            raise AuthError(KIND_NETWORK, '连接 GitHub 超时。', str(exc)) from exc

    @staticmethod
    def _parse(status: int, raw: bytes, what: str) -> dict:
        text = raw.decode('utf-8', errors='replace').strip()
        if not text:
            raise AuthError(KIND_API, f'GitHub 返回了空响应（{what}）。',
                            f'HTTP {status}')
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # 典型场景：代理软件返回了自己的 HTML 错误页
            raise AuthError(
                KIND_PARSE, 'GitHub 的响应无法解析，可能被代理拦截了。',
                f'HTTP {status}, body[:200]={text[:200]!r}') from exc
        if not isinstance(data, dict):
            raise AuthError(KIND_PARSE, f'GitHub 返回了非预期的数据（{what}）。',
                            f'{type(data).__name__}')
        return data

    # -- 协议 ------------------------------------------------------

    def post_form(self, url: str, fields: dict) -> tuple[int, dict]:
        body = urllib.parse.urlencode(fields).encode('ascii')
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Accept', 'application/json')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        req.add_header('User-Agent', USER_AGENT)
        status, raw = self._open(req)
        return status, self._parse(status, raw, 'POST ' + url.rsplit('/', 1)[-1])

    def get_json(self, url: str, token: str) -> tuple[int, dict]:
        req = urllib.request.Request(url, method='GET')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('Authorization', f'Bearer {token}')
        req.add_header('X-GitHub-Api-Version', '2022-11-28')
        req.add_header('User-Agent', USER_AGENT)
        label = url[len(API_ROOT):] if url.startswith(API_ROOT) else url
        status, raw = self._open(req)
        return status, self._parse(status, raw, 'GET ' + label)


def _ensure_transport(transport: Transport | None) -> Transport:
    return transport if transport is not None else UrllibTransport()


def resolve_client_id(explicit: str | None = None) -> str:
    """依次从 显式参数 → 环境变量 → 内置常量 取 client_id。"""
    import os
    for candidate in (explicit, os.environ.get(CLIENT_ID_ENV), DEFAULT_CLIENT_ID):
        if candidate and candidate.strip():
            return candidate.strip()
    raise AuthError(
        KIND_CONFIG,
        '还没有配置 GitHub OAuth 应用，无法开始授权。',
        f'请创建 OAuth App 并把 client_id 填入 core/ghauth.py 的 DEFAULT_CLIENT_ID，'
        f'或设置环境变量 {CLIENT_ID_ENV}。')


# ───────────────────────────── 协议三步 ─────────────────────────────

def request_device_code(client_id: str, scope: str = DEFAULT_SCOPE, *,
                        transport: Transport | None = None) -> DeviceCode:
    """第一步：申请设备码。"""
    if not client_id:
        raise AuthError(KIND_CONFIG, 'client_id 为空。')

    status, data = _ensure_transport(transport).post_form(
        DEVICE_CODE_URL, {'client_id': client_id, 'scope': scope})

    if 'user_code' not in data:
        err = data.get('error', f'HTTP {status}')
        raise AuthError(KIND_API, '申请设备码失败。',
                        f'{err}: {data.get("error_description", "")}'.strip())

    return DeviceCode(
        device_code=data['device_code'],
        user_code=data['user_code'],
        verification_uri=data.get('verification_uri', 'https://github.com/login/device'),
        expires_in=int(data.get('expires_in', 900)),
        interval=max(MIN_POLL_INTERVAL, int(data.get('interval', MIN_POLL_INTERVAL))),
        verification_uri_complete=data.get('verification_uri_complete', ''),
    )


def _cancellable_sleep(seconds: float, should_cancel: Callable[[], bool] | None) -> bool:
    """切片睡眠，让「取消」能在一瞬间生效，而不是等满一个轮询周期。

    返回 True 表示被取消。
    """
    if should_cancel is None:
        time.sleep(seconds)
        return False
    step = 0.2
    waited = 0.0
    while waited < seconds:
        if should_cancel():
            return True
        time.sleep(min(step, seconds - waited))
        waited += step
    return bool(should_cancel())


def poll_access_token(client_id: str, device: DeviceCode, *,
                      transport: Transport | None = None,
                      should_cancel: Callable[[], bool] | None = None,
                      on_pending: Callable[[float], None] | None = None,
                      clock: Callable[[], float] = time.monotonic,
                      sleep: Callable[[float, Callable[[], bool] | None], bool] = _cancellable_sleep,
                      ) -> Token:
    """第二步：轮询换 token。

    ``on_pending(剩余秒数)`` 每次等待前后回调一次，供界面显示倒计时。
    ``clock`` / ``sleep`` 可注入，自测时即可瞬间跑完 15 分钟的过期分支。
    """
    if not client_id:
        raise AuthError(KIND_CONFIG, 'client_id 为空。')

    t = _ensure_transport(transport)
    interval = max(MIN_POLL_INTERVAL, device.interval)
    deadline = clock() + max(1, device.expires_in)

    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise AuthError(KIND_EXPIRED,
                            '授权码已过期，请重新发起绑定。',
                            f'expires_in={device.expires_in}s')

        if on_pending is not None:
            on_pending(remaining)

        if sleep(interval, should_cancel):
            raise AuthError(KIND_CANCELLED, '已取消绑定。')

        if should_cancel is not None and should_cancel():
            raise AuthError(KIND_CANCELLED, '已取消绑定。')

        _, data = t.post_form(TOKEN_URL, {
            'client_id': client_id,
            'device_code': device.device_code,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        })

        token = data.get('access_token')
        if token:
            return Token(
                access_token=str(token),
                scope=str(data.get('scope', '')),
                token_type=str(data.get('token_type', 'bearer')),
                refresh_token=str(data.get('refresh_token', '') or ''),
                expires_in=int(data.get('expires_in', 0) or 0),
                raw=data,
            )

        error = str(data.get('error', ''))

        if error == 'authorization_pending':
            # 用户还没在网页上点完 —— 正常，继续等
            continue

        if error == 'slow_down':
            # 我们问得太勤了，退避 5 秒（协议规定）
            interval += 5
            continue

        if error == 'expired_token':
            raise AuthError(KIND_EXPIRED, '授权码已过期，请重新发起绑定。',
                            data.get('error_description', ''))

        if error == 'access_denied':
            raise AuthError(KIND_DENIED,
                            '你在 GitHub 上拒绝了这次授权。',
                            data.get('error_description', ''))

        raise AuthError(KIND_API, 'GitHub 拒绝了这次授权请求。',
                        f'{error}: {data.get("error_description", "")}'.strip())


def fetch_account(token: str, *, transport: Transport | None = None) -> Account:
    """第三步：用 token 读账号信息，顺便验证 token 真的可用。"""
    status, data = _ensure_transport(transport).get_json(f'{API_ROOT}/user', token)

    if status == 401:
        raise AuthError(KIND_API, '这枚令牌已失效，需要重新授权。', 'HTTP 401')
    if 'login' not in data:
        raise AuthError(KIND_API, '读取账号信息失败。',
                        f'HTTP {status}: {data.get("message", "")}'.strip())

    return Account(
        login=str(data['login']),
        name=str(data.get('name') or ''),
        avatar_url=str(data.get('avatar_url') or ''),
        id=int(data.get('id', 0) or 0),
    )


def verify_token(token: str, *, transport: Transport | None = None) -> bool:
    """轻量校验：token 现在还有效吗？失效返回 False（不抛异常）。"""
    try:
        fetch_account(token, transport=transport)
        return True
    except AuthError as exc:
        if exc.kind in (KIND_API, KIND_PARSE):
            return False
        raise


def authorize(client_id: str | None = None, scope: str = DEFAULT_SCOPE, *,
              transport: Transport | None = None,
              on_code: Callable[[DeviceCode], None],
              should_cancel: Callable[[], bool] | None = None,
              on_pending: Callable[[float], None] | None = None,
              clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float, Callable[[], bool] | None], bool] = _cancellable_sleep,
              ) -> tuple[Token, Account]:
    """把三步串起来，供界面一次调用。

    ``on_code`` 在拿到用户码后立刻回调 —— 界面这时才把码显示出来，
    不要在等待期间一直被轮询阻塞。

    ``clock`` / ``sleep`` 只为了自测能秒级跑完，界面用默认值即可。
    """
    cid = resolve_client_id(client_id)
    device = request_device_code(cid, scope, transport=transport)
    on_code(device)
    token = poll_access_token(cid, device, transport=transport,
                              should_cancel=should_cancel, on_pending=on_pending,
                              clock=clock, sleep=sleep)
    account = fetch_account(token.access_token, transport=transport)
    return token, account
