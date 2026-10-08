# -*- coding: utf-8 -*-
"""离屏 UI 截图：不开真窗口，直接把界面渲染成 PNG，用于开发期自查布局。

用法（在 pushnote 目录下）::

    .venv\\Scripts\\python.exe tools\\uishot.py [输出目录]

走 ``QT_QPA_PLATFORM=offscreen``，不需要真实屏幕，也不会弹窗打断你。
配置目录会重定向到临时目录，**不会碰 ~/.pushnote 里的真实配置**。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 必须在导入 PySide6 之前设置。
# 默认走 offscreen（安静、不需要屏幕），但 offscreen 下 Qt 的字体库是空的，
# 中文会渲染成方块 —— 要验证真实字体请加 --live（窗口会被挪到屏幕外）。
if '--live' not in sys.argv:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('PUSHNOTE_HOME', str(Path(tempfile.gettempdir()) / 'pushnote_uitest'))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402

from app.main import build_app  # noqa: E402
from app.window import FreePushWindow  # noqa: E402

SAMPLE = """16：Spring 的 IoC 容器是什么？

IoC 是 Inversion of Control，控制反转。它把对象的创建与依赖装配交给容器统一
管理，对象自己不再负责 new 依赖对象。

可以这样理解：以前是自己做饭，现在改成了点外卖——你需要什么，容器就给你什么，
你不用关心中间是怎么做出来的。

容器主要做这三件事：
  1. 扫描并注册 BeanDefinition
  2. 按依赖关系完成实例化与属性注入
  3. 管理完整生命周期：初始化、使用、销毁

常见实现有两种：BeanFactory 是懒加载，用到才创建；ApplicationContext 在启动时
就预实例化，功能更全，日常开发中用得最多。

30：软换行的行号测试

下面这一段是一整行、中间没有任何换行符的长文本，用来验证窗口变窄时续行的行号位置会有一个淡色小点——这一段会一直写下去直到它必然超过窗口宽度为止，这样才能看清续行的效果以及它的标记。
"""


def main() -> int:
    live = '--live' in sys.argv
    positional = [a for a in sys.argv[1:] if not a.startswith('--')]
    out_dir = Path(positional[0]) if positional else Path(tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)

    app = build_app([])
    win = FreePushWindow()
    win.resize(1200, 760)
    if live:
        win.move(-4000, -4000)      # 挪出可见区域，不打扰正在用电脑的人
    win.show()

    produced: list[Path] = []

    def shoot(name: str) -> None:
        app.processEvents()
        path = out_dir / name
        win.grab().save(str(path))
        produced.append(path)

    def run() -> None:
        shoot('ui_01_empty.png')                    # 空态

        sample = out_dir / 'ui_sample.txt'
        sample.write_text(SAMPLE, encoding='utf-8', newline='\r\n')
        win.load_path(str(sample))
        shoot('ui_02_editing.png')                  # 正常编辑态（含行号）

        win.toggle_panel(False)                     # 右栏收成窄条
        shoot('ui_03_rail.png')

        win.toggle_panel(True)
        win.toggle_sidebar()                        # 左栏收起（工具栏应出现「显示侧栏」）
        shoot('ui_04_no_sidebar.png')

        win.toggle_sidebar()                        # 再展开回来
        win.editor.set_font_size(22)                # 等价于 Ctrl+滚轮放大
        shoot('ui_05_zoom.png')

        for p in produced:
            print(p)
        app.quit()

    QTimer.singleShot(700, run)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
