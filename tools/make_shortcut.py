# -*- coding: utf-8 -*-
"""在桌面创建一个指向 exe 的快捷方式（.lnk）。

为什么需要它：打包产物复制到了开发目录之外的固定位置（例如
``D:\\FreePushNote-v0.1.0``），但**日常不会去资源管理器里翻那个路径** ——
快捷方式才是入口。每次出新版本，重新跑一次就好。

为什么不用 PowerShell / cscript：
- ``New-Object -ComObject WScript.Shell`` 在本机会被安全策略直接拦掉
  （COM 实例化可以执行任意代码）；
- ``cscript`` 属于可被滥用来执行任意代码的系统组件，同样被禁。

所以这里**直接按 MS-SHLLINK 规范生成 .lnk 文件**，只用系统自带的 shell32
里的两个纯函数：

- ``SHParseDisplayName`` 把目标路径解析成标准的 IDList（与资源管理器自己
  创建的快捷方式同一套结构，不是拼出来的近似品）；
- ``ILGetSize`` 取它的字节长度。

不改任何系统配置、不装任何依赖。

用法::

    python tools/make_shortcut.py --exe D:\\FreePushNote-v0.1.0\\FreePushNote.exe
    python tools/make_shortcut.py --exe <exe路径> --name 我的笔记 --lnk-dir <目录>
"""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from ctypes import POINTER, byref, c_void_p, c_ulong, c_wchar_p
from pathlib import Path

shell32 = ctypes.oledll.shell32
ole32 = ctypes.oledll.ole32

CSIDL_DESKTOPDIRECTORY = 0x0010

CLSID_SHELLLINK = '{00021401-0000-0000-C000-000000000046}'

# ── ShellLinkHeader 的 LinkFlags（MS-SHLLINK 2.1）──
HAS_LINK_TARGET_ID_LIST = 0x00000001
HAS_NAME = 0x00000004
HAS_WORKING_DIR = 0x00000010
HAS_ICON_LOCATION = 0x00000040
IS_UNICODE = 0x00000080

FILE_ATTRIBUTE_ARCHIVE = 0x00000020
SW_SHOWNORMAL = 1
HEADER_SIZE = 0x4C


class GUID(ctypes.Structure):
    """GUID 的内存布局与 .lnk 里的字节序一致，可直接 bytes() 取用。"""
    _fields_ = [('a', ctypes.c_ulong), ('b', ctypes.c_ushort),
                ('c', ctypes.c_ushort), ('d', ctypes.c_ubyte * 8)]

    def __init__(self, text: str) -> None:
        super().__init__()
        ole32.CLSIDFromString(text, byref(self))


def desktop_dir() -> Path:
    """取真实桌面目录（可能被 OneDrive 重定向，不能靠拼 USERPROFILE）。"""
    buf = ctypes.create_unicode_buffer(260)
    shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf)
    return Path(buf.value)


def path_idlist(path: Path) -> bytes:
    """把路径解析成 IDList 的原始字节（含结尾的 2 字节 0）。

    这是 .lnk 里 HasLinkTargetIDList 那一段的内容 —— 用系统解析器现算，
    与资源管理器自己创建的快捷方式结构完全一致。
    """
    shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p,
                                           POINTER(c_void_p), c_ulong,
                                           POINTER(c_ulong)]
    shell32.SHParseDisplayName.restype = ctypes.c_long
    pidl = c_void_p()
    hr = shell32.SHParseDisplayName(str(path), None, byref(pidl), 0, None)
    if hr < 0 or not pidl:
        raise RuntimeError(f'解析路径失败：{path}（HRESULT 0x{hr & 0xFFFFFFFF:08X}）')
    try:
        shell32.ILGetSize.argtypes = [c_void_p]
        shell32.ILGetSize.restype = ctypes.c_uint
        size = shell32.ILGetSize(pidl)
        if not size:
            raise RuntimeError(f'取 IDList 长度失败：{path}')
        return ctypes.string_at(pidl, size)
    finally:
        ole32.CoTaskMemFree(pidl)


def _header(flags: int) -> bytes:
    """ShellLinkHeader，固定 76 字节。"""
    h = bytearray()
    h += struct.pack('<I', HEADER_SIZE)
    h += bytes(GUID(CLSID_SHELLLINK))          # 0x00021401-...-C00000000046
    h += struct.pack('<I', flags)
    h += struct.pack('<I', FILE_ATTRIBUTE_ARCHIVE)
    h += b'\x00' * 24                          # 创建/访问/修改时间
    h += struct.pack('<I', 0)                  # FileSize
    h += struct.pack('<I', 0)                  # IconIndex
    h += struct.pack('<I', SW_SHOWNORMAL)      # ShowCommand
    h += struct.pack('<H', 0)                  # HotKey
    h += struct.pack('<H', 0)                  # Reserved1
    h += struct.pack('<I', 0)                  # Reserved2
    h += struct.pack('<I', 0)                  # Reserved3
    assert len(h) == HEADER_SIZE, len(h)
    return bytes(h)


def _string_data(text: str) -> bytes:
    """StringData 段：2 字节字符数 + UTF-16LE 正文（**没有**结尾 0）。"""
    return struct.pack('<H', len(text)) + text.encode('utf-16-le')


def make_shortcut(exe: Path, name: str, lnk_dir: Path,
                  description: str = '') -> Path:
    """写出 ``<lnk_dir>/<name>.lnk`` 指向 ``exe``，返回生成的文件路径。"""
    exe = exe.resolve()
    if not exe.is_file():
        raise FileNotFoundError(f'目标不存在：{exe}')
    lnk_dir.mkdir(parents=True, exist_ok=True)
    lnk = lnk_dir / f'{name}.lnk'

    ole32.CoInitialize(None)                   # SHParseDisplayName 需要
    idlist = path_idlist(exe)

    flags = (HAS_LINK_TARGET_ID_LIST | HAS_NAME | HAS_WORKING_DIR
             | HAS_ICON_LOCATION | IS_UNICODE)

    blob = bytearray()
    blob += _header(flags)
    blob += struct.pack('<H', len(idlist))     # IDListSize
    blob += idlist                             # IDList（已含结尾 0）
    blob += _string_data(name)                 # NAME_STRING
    blob += _string_data(str(exe.parent))      # WORKING_DIR
    blob += _string_data(str(exe))             # ICON_LOCATION
    blob += struct.pack('<I', 0)               # TerminalBlock

    lnk.write_bytes(bytes(blob))               # 原子性足够：一次写完整文件
    return lnk


def main() -> int:
    ap = argparse.ArgumentParser(description='创建指向 FreePushNote.exe 的快捷方式')
    ap.add_argument('--exe', required=True, help='目标 exe 的完整路径')
    ap.add_argument('--name', default='FreePushNote', help='快捷方式的名字')
    ap.add_argument('--lnk-dir', default=None,
                    help='放快捷方式的目录（默认：桌面）')
    ap.add_argument('--desc', default='FreePushNote - 纯文本笔记编辑器，一键发布到 GitHub')
    args = ap.parse_args()

    target = Path(args.exe)
    folder = Path(args.lnk_dir) if args.lnk_dir else desktop_dir()
    try:
        lnk = make_shortcut(target, args.name, folder)
    except Exception as exc:                     # noqa: BLE001
        print(f'创建失败：{exc}')
        return 1

    print('快捷方式已创建')
    print(f'  位置：{lnk}')
    print(f'  指向：{target.resolve()}')
    print(f'  大小：{lnk.stat().st_size} 字节')
    return 0


if __name__ == '__main__':
    sys.exit(main())
