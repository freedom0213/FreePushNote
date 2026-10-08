# -*- coding: utf-8 -*-
"""认证层自测：用假传输把 Device Flow 的每条分支跑一遍，全程不联网。

覆盖的分支都是真实会遇到的情况，不是为了凑覆盖率：

* 用户正常授权
* 用户还在网页上犹豫（``authorization_pending``）
* 我们问得太勤，GitHub 让我们退避（``slow_down``）
* 用户在网页上点了拒绝（``access_denied``）
* 用户把界面开着去吃饭，码过期了（``expired_token`` 与本地超时两条路）
* 用户中途关掉对话框（取消）
* 代理坏了 / 连不上（网络错误）
* 代理返回自己的 HTML 错误页（解析失败）—— 这个最容易伪装成别的问题
* 令牌落盘不落明文、路径穿越被挡住

用法：
    .venv\\Scripts\\python.exe tools\\auth_selftest.py
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在导入 core.config 之前重定向，否则会写到真实用户目录
_TMP = Path(tempfile.mkdtemp(prefix='pushnote_auth_test_'))
os.environ['PUSHNOTE_HOME'] = str(_TMP)

from core import ghauth, secretstore  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = '') -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ok   {name}')
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f'  FAIL {name}  {extra}')


def expect_auth_error(name: str, kind: str, fn) -> None:
    """断言某段代码抛出指定种类的 AuthError。"""
    try:
        fn()
    except ghauth.AuthError as exc:
        check(f'{name} → {kind}', exc.kind == kind, f'实际为 {exc.kind}：{exc.message}')
    except Exception as exc:  # noqa: BLE001
        check(f'{name} → {kind}', False, f'抛出了 {type(exc).__name__}：{exc}')
    else:
        check(f'{name} → {kind}', False, '没有抛出异常')


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:  # noqa: BLE001
        return True
    return False


# ───────────────────────── 测试替身 ─────────────────────────

class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeSleep:
    """假睡眠：瞬间返回，但把「睡了多久」记下来，并把时钟往前推。"""

    def __init__(self, clock: FakeClock, cancel: bool = False) -> None:
        self.clock = clock
        self.cancel = cancel
        self.calls: list[float] = []

    def __call__(self, seconds: float, should_cancel) -> bool:
        self.calls.append(seconds)
        self.clock.advance(seconds)
        return self.cancel


class FakeTransport:
    def __init__(self, posts=None, gets=None) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, str]] = []
        self._posts = list(posts or [])
        self._gets = list(gets or [])

    def post_form(self, url: str, fields: dict):
        self.posts.append((url, fields))
        if not self._posts:
            raise AssertionError(f'意料之外的 POST：{url}')
        return self._posts.pop(0)

    def get_json(self, url: str, token: str):
        self.gets.append((url, token))
        if not self._gets:
            raise AssertionError(f'意料之外的 GET：{url}')
        return self._gets.pop(0)


DEVICE_OK = (200, {
    'device_code': 'dev-abc', 'user_code': 'WDJB-MJHT',
    'verification_uri': 'https://github.com/login/device',
    'verification_uri_complete': 'https://github.com/login/device?user_code=WDJB-MJHT',
    'expires_in': 900, 'interval': 5,
})
TOKEN_OK = (200, {'access_token': 'gho_TESTTOKEN1234567890', 'token_type': 'bearer',
                  'scope': 'repo,read:user'})
USER_OK = (200, {'login': 'freedom0213', 'name': 'Li Shichen',
                 'avatar_url': 'https://avatars.githubusercontent.com/u/1', 'id': 1})

CID = 'Ov23liTESTCLIENTID'


def make_device(**kw) -> ghauth.DeviceCode:
    base = dict(device_code='dev-abc', user_code='WDJB-MJHT',
                verification_uri='https://github.com/login/device',
                expires_in=900, interval=5)
    base.update(kw)
    return ghauth.DeviceCode(**base)


# ───────────────────────── 1. client_id 解析 ─────────────────────────

def test_client_id() -> None:
    print('\n[1] client_id 解析')
    check('显式传入优先', ghauth.resolve_client_id('explicit-id') == 'explicit-id')

    os.environ[ghauth.CLIENT_ID_ENV] = 'from-env'
    try:
        check('环境变量生效', ghauth.resolve_client_id(None) == 'from-env')
        check('显式参数仍优先于环境变量',
              ghauth.resolve_client_id('explicit-id') == 'explicit-id')
    finally:
        os.environ.pop(ghauth.CLIENT_ID_ENV, None)

    # 「未配置 client_id」这条分支：内置常量现在有值了，临时清空来验证它仍然可达
    # （将来有人把 DEFAULT_CLIENT_ID 留空时，这里就是唯一的保障）
    saved = ghauth.DEFAULT_CLIENT_ID
    ghauth.DEFAULT_CLIENT_ID = ''
    try:
        expect_auth_error('未配置 client_id', ghauth.KIND_CONFIG,
                          lambda: ghauth.resolve_client_id(None))
        check('空白 client_id 也算未配置',
              _raises(lambda: ghauth.resolve_client_id('   ')))
    finally:
        ghauth.DEFAULT_CLIENT_ID = saved


# ───────────────────────── 2. 申请设备码 ─────────────────────────

def test_device_code() -> None:
    print('\n[2] 申请设备码')
    t = FakeTransport(posts=[DEVICE_OK])
    d = ghauth.request_device_code(CID, transport=t)
    check('用户码解析正确', d.user_code == 'WDJB-MJHT')
    check('过期时间 900 秒', d.expires_in == 900)
    check('轮询间隔 5 秒', d.interval == 5)
    check('带上了 scope', t.posts[0][1]['scope'] == ghauth.DEFAULT_SCOPE)
    check('过期分钟数换算', d.expires_minutes == 15)

    t2 = FakeTransport(posts=[(200, {'error': 'device_flow_disabled',
                                     'error_description': 'Device flow is not enabled'})])
    expect_auth_error('应用未开启 Device Flow', ghauth.KIND_API,
                      lambda: ghauth.request_device_code(CID, transport=t2))

    # interval 缺失或过小都要被抬到协议下限
    t3 = FakeTransport(posts=[(200, {'device_code': 'd', 'user_code': 'A-B',
                                     'verification_uri': 'https://x', 'expires_in': 900})])
    check('interval 缺失时补下限 5',
          ghauth.request_device_code(CID, transport=t3).interval == 5)


# ───────────────────────── 3. 轮询状态机 ─────────────────────────

def test_poll() -> None:
    print('\n[3] 轮询换 token')

    # 3.1 第一次就拿到
    c = FakeClock()
    s = FakeSleep(c)
    t = FakeTransport(posts=[TOKEN_OK])
    tok = ghauth.poll_access_token(CID, make_device(), transport=t, clock=c, sleep=s)
    check('一次命中就返回 token', tok.access_token.startswith('gho_'))
    check('轮询前先等一个间隔', s.calls == [5.0])
    check('脱敏形式不泄露完整 token', tok.masked() == 'gho_…7890')

    # 3.2 先 pending 两次再成功
    c = FakeClock()
    s = FakeSleep(c)
    t = FakeTransport(posts=[
        (200, {'error': 'authorization_pending'}),
        (200, {'error': 'authorization_pending'}),
        TOKEN_OK,
    ])
    tok = ghauth.poll_access_token(CID, make_device(), transport=t, clock=c, sleep=s)
    check('pending 会继续等', tok.access_token.startswith('gho_'))
    check('共轮询 3 次', len(t.posts) == 3)
    check('间隔没有变化', s.calls == [5.0, 5.0, 5.0])

    # 3.3 slow_down 要退避
    c = FakeClock()
    s = FakeSleep(c)
    t = FakeTransport(posts=[(200, {'error': 'slow_down'}), TOKEN_OK])
    ghauth.poll_access_token(CID, make_device(), transport=t, clock=c, sleep=s)
    check('slow_down 后间隔 +5', s.calls == [5.0, 10.0])

    # 3.4 回调能报出剩余时间
    c = FakeClock()
    s = FakeSleep(c)
    seen: list[float] = []
    ghauth.poll_access_token(CID, make_device(), transport=FakeTransport(posts=[TOKEN_OK]),
                             clock=c, sleep=s, on_pending=seen.append)
    check('on_pending 拿到剩余秒数', seen and abs(seen[0] - 900) < 1)

    # 3.5 用户拒绝
    c = FakeClock()
    s = FakeSleep(c)
    expect_auth_error('用户拒绝授权', ghauth.KIND_DENIED, lambda: ghauth.poll_access_token(
        CID, make_device(), transport=FakeTransport(posts=[(200, {'error': 'access_denied'})]),
        clock=c, sleep=s))

    # 3.6 服务端判定过期
    c = FakeClock()
    s = FakeSleep(c)
    expect_auth_error('设备码过期（服务端）', ghauth.KIND_EXPIRED, lambda: ghauth.poll_access_token(
        CID, make_device(), transport=FakeTransport(posts=[(200, {'error': 'expired_token'})]),
        clock=c, sleep=s))

    # 3.7 一直 pending 直到本地超时（把时钟交给假睡眠推进）
    c2 = FakeClock()
    s2 = FakeSleep(c2)
    expect_auth_error('一直 pending 到本地超时', ghauth.KIND_EXPIRED, lambda: ghauth.poll_access_token(
        CID, make_device(expires_in=20),
        transport=FakeTransport(posts=[(200, {'error': 'authorization_pending'})] * 50),
        clock=c2, sleep=s2))

    # 3.8 别的错误码要走 API 分支
    c = FakeClock()
    s = FakeSleep(c)
    expect_auth_error('未知错误码', ghauth.KIND_API, lambda: ghauth.poll_access_token(
        CID, make_device(), transport=FakeTransport(posts=[(200, {'error': 'incorrect_client_credentials'})]),
        clock=c, sleep=s))

    # 3.9 取消
    c = FakeClock()
    s = FakeSleep(c, cancel=True)
    expect_auth_error('用户取消', ghauth.KIND_CANCELLED, lambda: ghauth.poll_access_token(
        CID, make_device(), transport=FakeTransport(posts=[TOKEN_OK]), clock=c, sleep=s))


# ───────────────────────── 4. 账号信息 ─────────────────────────

def test_account() -> None:
    print('\n[4] 读取账号信息')
    acc = ghauth.fetch_account('t', transport=FakeTransport(gets=[USER_OK]))
    check('login 解析正确', acc.login == 'freedom0213')
    check('display 带姓名', acc.display == 'Li Shichen（freedom0213）')

    acc2 = ghauth.fetch_account('t', transport=FakeTransport(
        gets=[(200, {'login': 'sonly', 'id': 2})]))
    check('没有姓名时只显示 login', acc2.display == 'sonly')

    expect_auth_error('令牌失效 401', ghauth.KIND_API,
                      lambda: ghauth.fetch_account('t', transport=FakeTransport(
                          gets=[(401, {'message': 'Bad credentials'})])))

    check('verify_token 失效返回 False',
          ghauth.verify_token('t', transport=FakeTransport(
              gets=[(401, {'message': 'Bad credentials'})])) is False)
    check('verify_token 有效返回 True',
          ghauth.verify_token('t', transport=FakeTransport(gets=[USER_OK])) is True)


# ───────────────────────── 5. 传输层错误 ─────────────────────────

def test_transport_errors() -> None:
    print('\n[5] 传输层错误')
    import urllib.error

    tr = ghauth.UrllibTransport.__new__(ghauth.UrllibTransport)

    # 代理返回 HTML 错误页 —— 最容易伪装成「认证失败」的那种
    try:
        tr._parse(200, b'<html><body>Proxy Error</body></html>', 'POST token')
    except ghauth.AuthError as exc:
        check('HTML 响应判定为解析失败', exc.kind == ghauth.KIND_PARSE, exc.kind)
    else:
        check('HTML 响应判定为解析失败', False, '没有抛出')

    try:
        tr._parse(200, b'', 'POST token')
    except ghauth.AuthError as exc:
        check('空响应判定为 API 错误', exc.kind == ghauth.KIND_API, exc.kind)
    else:
        check('空响应判定为 API 错误', False, '没有抛出')

    check('正常 JSON 能解析', tr._parse(200, b'{"ok":1}', 'x') == {'ok': 1})

    # 连不上要变成 KIND_NETWORK 而不是原始 URLError 冒到界面上
    class _Boom:
        def open(self, req, timeout=None):
            raise urllib.error.URLError('connection refused')

    boom = ghauth.UrllibTransport.__new__(ghauth.UrllibTransport)
    boom._opener = _Boom()
    boom._timeout = 1
    expect_auth_error('连不上 GitHub', ghauth.KIND_NETWORK,
                      lambda: boom.post_form(ghauth.TOKEN_URL, {}))


# ───────────────────────── 6. 令牌存储 ─────────────────────────

def test_secretstore() -> None:
    print('\n[6] 令牌存储')
    print(f'  （后端：{secretstore.BACKEND_LABEL}）')

    token = 'gho_SECRET_abcdefghijklmnop'
    path = secretstore.save_token('freedom0213', token)

    check('可以读回原值', secretstore.load_token('freedom0213') == token)
    raw = path.read_bytes()
    leaked = token.encode() in raw
    if secretstore.BACKEND == 'dpapi':
        # 加密后端要额外确认：连 base64(明文) 都不能出现（防止「只是套了层编码」）
        leaked = leaked or base64.b64encode(token.encode()) in raw
    check('落盘文件里没有明文',
          not leaked, '发现了明文 token！' if secretstore.BACKEND == 'dpapi'
          else '（当前为未加密降级模式，仅确认未直接写入原始字节）')
    check('在凭据目录内',
          str(path).startswith(str(secretstore.CRED_DIR)), str(path))
    check('出现在账号列表里', 'freedom0213' in secretstore.list_accounts())
    check('has_token 为真', secretstore.has_token('freedom0213'))

    check('不存在的账号返回 None', secretstore.load_token('nobody') is None)
    check('删除成功', secretstore.delete_token('freedom0213'))
    check('删除后读不到', secretstore.load_token('freedom0213') is None)
    check('重复删除返回 False', secretstore.delete_token('freedom0213') is False)

    # 路径穿越必须被挡住
    for evil in ('../../etc/passwd', '..', 'a/b', '..\\..\\win.ini'):
        try:
            p = secretstore.account_path(evil)
        except ValueError:
            check(f'路径穿越被拒：{evil}', True)
            continue
        inside = secretstore.CRED_DIR.resolve() in p.resolve().parents or \
            p.resolve().parent == secretstore.CRED_DIR.resolve()
        check(f'路径穿越被拒：{evil}', inside, f'越界到 {p}')

    # 损坏文件要抛 OSError，而不是返回半截 token
    bad = secretstore.account_path('broken')
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('这显然不是 base64', encoding='utf-8')
    try:
        secretstore.load_token('broken')
    except OSError:
        check('损坏凭据抛 OSError', True)
    else:
        check('损坏凭据抛 OSError', False, '竟然读成功了')


# ───────────────────────── 7. 全流程串起来 ─────────────────────────

def test_end_to_end() -> None:
    print('\n[7] 全流程（申请码 → 轮询 → 读账号）')
    c = FakeClock()
    s = FakeSleep(c)
    t = FakeTransport(
        posts=[DEVICE_OK, (200, {'error': 'authorization_pending'}), TOKEN_OK],
        gets=[USER_OK])

    shown: list[ghauth.DeviceCode] = []
    token, acc = ghauth.authorize(
        CID, transport=t, on_code=shown.append, should_cancel=lambda: False,
        on_pending=lambda _r: None, clock=c, sleep=s)
    check('on_code 先于轮询被调用', len(shown) == 1)
    check('用户码传给了界面', shown[0].user_code == 'WDJB-MJHT')
    check('拿到 token', token.access_token.startswith('gho_'))
    check('拿到账号', acc.login == 'freedom0213')
    check('请求顺序正确（1 次设备码 + 2 次轮询 + 1 次用户）',
          len(t.posts) == 3 and len(t.gets) == 1)
    check('总共只等了 2 个间隔', s.calls == [5.0, 5.0])

    # 缺少 client_id 时 authorize 应该在发请求之前就失败
    saved = ghauth.DEFAULT_CLIENT_ID
    ghauth.DEFAULT_CLIENT_ID = ''
    try:
        expect_auth_error('未配置时 authorize 提前失败', ghauth.KIND_CONFIG,
                          lambda: ghauth.authorize(None, on_code=lambda _d: None))
    finally:
        ghauth.DEFAULT_CLIENT_ID = saved


def main() -> int:
    print('=' * 62)
    print('FreePushNote 认证层自测（不联网）')
    print('=' * 62)
    test_client_id()
    test_device_code()
    test_poll()
    test_account()
    test_transport_errors()
    test_secretstore()
    test_end_to_end()

    print('\n' + '=' * 62)
    print(f'通过 {PASS} / {PASS + FAIL}')
    if FAILURES:
        print('失败项：')
        for name in FAILURES:
            print(f'  - {name}')
    print('=' * 62)

    # 清掉自测产生的临时目录（里面可能有测试令牌）
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())
