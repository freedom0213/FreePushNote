# -*- coding: utf-8 -*-
"""把 FreePushNote 打包成可分发程序。

产出两个，对应 GitHub Releases 上两种下载：

    dist/FreePushNote-v0.1.0-win64.zip   onedir 打包后压缩 —— 启动快，解压即用
    dist/FreePushNote-v0.1.0.exe         onefile 单文件 —— 双击就跑，启动慢几秒

为什么两种都出：**启动速度**与**分发便利**各占一头，用户口味不同；多跑一遍
PyInstaller 的成本，远低于让用户去理解这些差别。发布时在 release 说明里写一句
区别就够了。

⚠️ 依赖 PyInstaller，且**必须装在项目自己的 .venv 里** —— 它要收集那个环境中的
PySide6。运行时不需要 PyInstaller。

用法（在项目根目录下）：
    python tools/build_exe.py              # 两个都打
    python tools/build_exe.py --onedir     # 只打 zip 那个
    python tools/build_exe.py --onefile    # 只打单文件那个
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402  版本号只维护一处：core/config.py 的 APP_VERSION

DIST = ROOT / 'dist'
BUILD = ROOT / 'build'
ICON = ROOT / 'assets' / 'icon' / 'app.ico'


def version_file(path: Path, version: str) -> None:
    """生成 exe 的版本信息（会显示在「右键 → 属性 → 详细信息」里）。

    没有它，exe 属性页是一堆空白 —— 一眼就是「随手打的包」；
    有了才像一份正式发布的东西，用户也才能确认自己下的是哪个版本。
    """
    nums = ', '.join(str(int(p)) for p in (version.split('.') + ['0', '0', '0'])[:4])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404B0', [
      StringStruct('CompanyName', 'freedom0213'),
      StringStruct('FileDescription', 'FreePushNote - 纯文本笔记编辑器，一键发布到 GitHub'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'FreePushNote'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'FreePushNote.exe'),
      StringStruct('ProductName', 'FreePushNote'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""", encoding='utf-8')


def build(*, onefile: bool, out_dir: Path = DIST) -> None:
    """跑一遍 PyInstaller。"""
    mode = '单文件（onefile）' if onefile else '文件夹（onedir）'
    print(f'\n{"=" * 64}\n打包：{mode}\n{"=" * 64}', flush=True)

    name = f'FreePushNote-v{config.APP_VERSION}' if onefile else 'FreePushNote'
    vf = BUILD / 'version_info.txt'
    version_file(vf, config.APP_VERSION)

    args = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--windowed',      # GUI 程序，不弹控制台
        '--name', name,
        '--icon', str(ICON),
        '--version-file', str(vf),
        '--distpath', str(out_dir), '--workpath', str(BUILD),
        # 资源：站点模板 + 本地化的前端资源（离线也能生成文档站），以及应用图标。
        # 刻意逐个列出而不是整个 assets/ —— 那里还躺着 1.4MB 的母版图
        # （source.jpg / app.png），运行时一个都用不到。
        '--add-data', 'assets/docsify;assets/docsify',
        '--add-data', 'assets/icon/app.ico;assets/icon',
        '--add-data', 'templates;templates',
        '--onefile' if onefile else '--onedir',
        'app/main.py',
    ]
    subprocess.run(args, cwd=ROOT, check=True)


def zip_dir(src: Path, out: Path) -> None:
    """把文件夹压成 zip，**保留顶层目录**。

    保留它，用户解压后得到的是一个干净的文件夹；不然一堆 dll 会直接摊在
    桌面上，那不是「收到一个软件」的观感。
    """
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(src.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(src.parent))


def size_mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1024 / 1024
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file()) / 1024 / 1024


def main() -> int:
    ap = argparse.ArgumentParser(description='打包 FreePushNote')
    ap.add_argument('--onefile', action='store_true', help='只打单文件 exe')
    ap.add_argument('--onedir', action='store_true', help='只打文件夹版 zip')
    ap.add_argument('--out', default=str(DIST),
                    help='输出目录（默认 dist）。产物正在运行时会锁住 dist 里的 exe，'
                         '这时指到别处即可，不必关掉程序')
    args = ap.parse_args()
    out_dir = Path(args.out).resolve()
    do_onedir = args.onedir or not (args.onefile or args.onedir)
    do_onefile = args.onefile or not (args.onefile or args.onedir)

    if not ICON.is_file():
        raise SystemExit(f'缺少图标文件：{ICON}\n先跑 tools/make_icon.py 生成它。')

    version = config.APP_VERSION
    print(f'FreePushNote v{version}  ·  输出目录 {out_dir}')
    out_dir.mkdir(parents=True, exist_ok=True)

    made: list[Path] = []

    if do_onedir:
        build(onefile=False, out_dir=out_dir)
        folder = out_dir / 'FreePushNote'
        zip_path = out_dir / f'FreePushNote-v{version}-win64.zip'
        print(f'压缩 → {zip_path.name}', flush=True)
        zip_dir(folder, zip_path)
        made.append(zip_path)

    if do_onefile:
        build(onefile=True, out_dir=out_dir)
        exe = out_dir / f'FreePushNote-v{version}.exe'
        if not exe.is_file():
            raise SystemExit(f'预期产物不存在：{exe}')
        made.append(exe)

    print(f'\n{"=" * 64}\n完成\n{"=" * 64}')
    for p in made:
        print(f'  {p.name:42s} {size_mb(p):6.1f} MB')
    print('\n发布到 GitHub Releases 时：')
    print('  1. 把上面这两个文件作为 Assets 上传')
    print('  2. 在 release 说明里写清区别（zip 启动快 / exe 单文件省事）')
    print('  3. 提醒用户首次运行可能弹「未知发布者」—— 没有代码签名都会这样，'
          '点「更多信息 → 仍要运行」即可')
    return 0


if __name__ == '__main__':
    sys.exit(main())
