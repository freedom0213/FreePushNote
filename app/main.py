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
    app = build_app()
    window = FreePushWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
