# -*- coding: utf-8 -*-
"""访问令牌的本地存储。

原则：**不落明文。**

Windows 上用 DPAPI（``CryptProtectData``）加密后再写盘。
DPAPI 是 Windows 自己的凭据保护机制，密钥绑定当前用户账户——
换一个 Windows 用户登录就读不出来，文件被拷走也没用。
这也正是「凭据管理器」底层用的东西，所以从安全角度讲它比自建加密更标准。

实现细节
--------
* 走 ``ctypes`` 直接调 ``crypt32``：不引第三方库（``keyring`` / ``pywin32``），
  打包成 exe 时体积和兼容性都更可控。
* 不用「自己拿密码派生密钥」那套：那需要用户记密码，而这个软件是自用工具，
  引入一个密码只会在体验上减分，安全增益也不如 DPAPI。

非 Windows 平台
---------------
降级为 0600 权限的明文文件，并把 :data:`USING_PLAINTEXT` 置真，
让界面能如实提示用户，而不是假装安全。
"""
from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

from . import config as core_config

#: 存在 ~/.pushnote/credentials/ 下，与绑定配置分开，便于单独清理
CRED_DIR = core_config.CONFIG_DIR / 'credentials'

_IS_WINDOWS = sys.platform == 'win32'
_ACCOUNT_RE = re.compile(r'[^A-Za-z0-9._-]')

#: 非 Windows 平台会置真；界面据此提示「当前平台未加密存储」
USING_PLAINTEXT = not _IS_WINDOWS

_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_DESCRIPTION = 'FreePushNote GitHub token'


# ───────────────────────────── DPAPI ─────────────────────────────

if _IS_WINDOWS:  # pragma: no cover - 平台相关
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.restype = wintypes.BOOL

    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL

    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    def _blob_of(data: bytes):
        buf = ctypes.create_string_buffer(data, max(len(data), 1))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _dpapi_protect(data: bytes) -> bytes:
        blob_in, _keep = _blob_of(data)
        blob_out = _Blob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(blob_in), _DESCRIPTION, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            raise OSError(ctypes.get_last_error(), 'CryptProtectData 失败')
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)

    def _dpapi_unprotect(data: bytes) -> bytes:
        blob_in, _keep = _blob_of(data)
        blob_out = _Blob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            raise OSError(ctypes.get_last_error(), 'CryptUnprotectData 失败')
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)

    BACKEND = 'dpapi'
    BACKEND_LABEL = 'Windows DPAPI（绑定当前用户账户）'

else:  # pragma: no cover - 平台相关
    def _dpapi_protect(data: bytes) -> bytes:
        return data

    def _dpapi_unprotect(data: bytes) -> bytes:
        return data

    BACKEND = 'plain'
    BACKEND_LABEL = '明文文件（当前平台不支持 DPAPI）'


# ───────────────────────────── 公开接口 ─────────────────────────────

def sanitize_account(account: str) -> str:
    """把 GitHub 用户名收敛成安全文件名，杜绝 ``../`` 这类路径穿越。"""
    name = _ACCOUNT_RE.sub('_', (account or '').strip())
    if not name or name in ('.', '..'):
        raise ValueError(f'非法的账号名：{account!r}')
    return name


def account_path(account: str) -> Path:
    return CRED_DIR / f'{sanitize_account(account)}.bin'


def has_token(account: str) -> bool:
    try:
        return account_path(account).is_file()
    except ValueError:
        return False


def save_token(account: str, token: str) -> Path:
    """加密写入。文件内容里不含明文 token。"""
    path = account_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _dpapi_protect(token.encode('utf-8'))
    payload = base64.b64encode(blob).decode('ascii')

    tmp = path.with_suffix('.tmp')
    tmp.write_text(payload, encoding='ascii')
    _restrict(tmp)
    os.replace(tmp, path)          # 原子替换
    _restrict(path)
    return path


def load_token(account: str) -> str | None:
    """读出并解密；文件不存在返回 None，损坏则抛 OSError。"""
    path = account_path(account)
    if not path.is_file():
        return None
    try:
        blob = base64.b64decode(path.read_text(encoding='ascii').strip(), validate=True)
        return _dpapi_unprotect(blob).decode('utf-8')
    except ValueError as exc:
        raise OSError(f'凭据文件已损坏：{path}') from exc


def delete_token(account: str) -> bool:
    path = account_path(account)
    if path.is_file():
        path.unlink()
        return True
    return False


def list_accounts() -> list[str]:
    """已保存凭据的账号列表（按名称排序）。"""
    if not CRED_DIR.is_dir():
        return []
    return sorted(p.stem for p in CRED_DIR.glob('*.bin'))


def _restrict(path: Path) -> None:
    """尽量收紧权限。

    Windows 上这个调用基本是空操作（ACL 由 DPAPI + 用户目录保护），
    在类 Unix 上则把权限压到 0600。
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
