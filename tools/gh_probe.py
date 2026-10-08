# -*- coding: utf-8 -*-
"""真实网络的认证探针：不开界面，直接跑一遍 Device Flow。

用途有两个，都不是为了自测（自测见 ``tools/auth_selftest.py``，那个不联网）：

1. **验证 client_id / Device Flow / 代理链路**是否真的通 ——
   只申请设备码，不涉及用户操作，5 秒内出结果。
2. **无界面地绑定账号**（``--bind``）—— 排查问题时不必先跑起 GUI。

用法：
    .venv\\Scripts\\python.exe tools\\gh_probe.py              # 只申请设备码
    .venv\\Scripts\\python.exe tools\\gh_probe.py --bind       # 走完全流程并保存令牌
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ghauth, secretstore  # noqa: E402


def main() -> int:
    do_bind = '--bind' in sys.argv
    scope = ghauth.DEFAULT_SCOPE

    print('=' * 64)
    print('GitHub 认证探针')
    print('=' * 64)

    try:
        cid = ghauth.resolve_client_id()
    except ghauth.AuthError as exc:
        print(f'[x] {exc.message}')
        print(f'    {exc.detail}')
        return 1

    proxy = ghauth._auto_proxy() or '（直连，未走代理）'
    print(f'client_id  : {cid[:8]}…{cid[-4:]}')
    print(f'scope      : {scope}')
    print(f'代理        : {proxy}')
    print(f'令牌后端    : {secretstore.BACKEND_LABEL}')
    print('-' * 64)

    # ── 第 1 步：申请设备码 ────────────────────────────────
    try:
        t0 = time.monotonic()
        device = ghauth.request_device_code(cid, scope)
        dt = time.monotonic() - t0
    except ghauth.AuthError as exc:
        print(f'[x] 申请设备码失败（{exc.kind}）')
        print(f'    {exc.message}')
        if exc.detail:
            print(f'    {exc.detail}')
        print('\n排查方向：')
        print('  · kind=parse  → 代理软件把响应换成了自己的页面')
        print('  · kind=network→ 连不上 GitHub，检查代理')
        print('  · kind=api 且提到 device_flow → OAuth App 里没勾 Enable Device Flow')
        return 1

    print(f'[ok] 申请设备码成功（{dt:.2f}s）')
    print(f'     用户码   : {device.user_code}')
    print(f'     有效期   : {device.expires_in}s（约 {device.expires_minutes} 分钟）')
    print(f'     轮询间隔 : {device.interval}s')

    if not do_bind:
        print('\n（只验到第 1 步。要跑完整流程加 --bind）')
        return 0

    # ── 第 2 步：让用户去网页上输入 ────────────────────────
    print('-' * 64)
    print('请在浏览器打开：')
    print(f'  {device.verification_uri}')
    print(f'并输入这 8 位码：  {device.user_code}')
    print()
    print('等待授权中…（Ctrl+C 可取消）')

    try:
        token = ghauth.poll_access_token(
            cid, device,
            on_pending=lambda left: print(f'  …还剩 {int(left // 60)} 分 {int(left % 60)} 秒'),
        )
    except KeyboardInterrupt:
        print('\n[!] 已取消。')
        return 130
    except ghauth.AuthError as exc:
        print(f'\n[x] 授权失败（{exc.kind}）：{exc.message}')
        if exc.detail:
            print(f'    {exc.detail}')
        return 1

    print(f'\n[ok] 拿到令牌：{token.masked()}  scope={token.scope or "(未返回)"}')

    # ── 第 3 步：读账号信息并落盘 ──────────────────────────
    try:
        account = ghauth.fetch_account(token.access_token)
    except ghauth.AuthError as exc:
        print(f'[x] 读取账号失败（{exc.kind}）：{exc.message}')
        return 1

    path = secretstore.save_token(account.login, token.access_token)
    print(f'[ok] 账号：{account.display}  (id={account.id})')
    print(f'[ok] 令牌已加密保存到 {path}')
    print(f'     后端：{secretstore.BACKEND_LABEL}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
