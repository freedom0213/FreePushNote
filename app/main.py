# -*- coding: utf-8 -*-
"""FreePushNote 入口。

直接运行::

    .venv\\Scripts\\python.exe app\\main.py

关掉高 DPI 缩放取整，否则 125% 缩放下 1px 边框会时有时无。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import theme  # noqa: E402
from app.window import FreePushWindow  # noqa: E402
from core import config as core_config  # noqa: E402


def _install_crash_log() -> None:
    """把未捕获的异常写进日志文件。

    打包成 exe 之后**没有控制台**，异常会静默消失 —— 用户看到的只是
    「双击了，窗口闪一下就没了」，然后只能说「打不开」，谁也查不出原因。
    留一份日志到 ``~/.pushnote/logs/`` 是给这种情况准备的关键线索。

    仍然调用默认的 excepthook：开发时该在终端里看到的还是要看到。
    """
    import traceback
    from datetime import datetime

    def hook(exc_type, exc, tb) -> None:
        try:
            log_dir = core_config.CONFIG_DIR / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            (log_dir / f'crash-{stamp}.log').write_text(
                ''.join(traceback.format_exception(exc_type, exc, tb)),
                encoding='utf-8')
        except Exception:       # noqa: BLE001 - 记日志本身绝不能把程序带崩
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def build_app(argv: list[str] | None = None) -> QApplication:
    """创建并配置好 QApplication（UI 截图脚本也复用它）。"""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName('FreePushNote')
    app.setApplicationDisplayName('FreePushNote')
    app.setOrganizationName('freedom0213')

    ui_font = QFont()
    ui_font.setFamilies(['Microsoft YaHei UI', 'Segoe UI', 'Noto Sans SC'])
    ui_font.setPixelSize(int(theme.FS_UI))
    app.setFont(ui_font)

    app.setStyleSheet(theme.qss())
    return app


def main() -> int:
    _install_crash_log()
    app = build_app()
    window = FreePushWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
