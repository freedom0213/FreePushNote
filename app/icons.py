# -*- coding: utf-8 -*-
"""矢量图标：全部内联 SVG，不依赖外部资源文件。

用法::

    from app import icons
    btn.setIcon(icons.icon('close', icons.CLOSE_NORMAL, 16))

每套路径都是 16×16 或 12×12 的线性图标，描边宽度 1.1–1.8，
与设计稿（Ardot 733847576651907）保持一致。
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 颜色（与 theme 保持一致，但这里独立定义避免循环导入）
C_GHOST = '#4A4A4C'
C_WEAK = '#6A6A6A'
C_MUTED = '#8C8C8C'
C_SECOND = '#9D9D9D'
C_BODY = '#C8C8C8'
C_PRIMARY = '#1177BB'
C_SUCCESS = '#89D185'
C_ERROR = '#F48771'
C_WARNING = '#CCA700'
C_WHITE = '#FFFFFF'

_TEMPLATES: dict[str, str] = {
    # ── 应用标识：文档 + 上传箭头 ──
    'app': ('<svg viewBox="0 0 24 24" fill="none">'
            '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" '
            'stroke="{c}" stroke-width="1.8" stroke-linejoin="round"/>'
            '<path d="M14 3v5h5" stroke="{c}" stroke-width="1.8" stroke-linejoin="round"/>'
            '<path d="M12 17.5v-5.5M9.6 14.5 12 12l2.4 2.5" stroke="{c2}" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>'),

    # ── 窗口控制 ──
    'min': ('<svg viewBox="0 0 12 12"><path d="M2 6h8" stroke="{c}" stroke-width="1.1"/></svg>'),
    'max': ('<svg viewBox="0 0 12 12" fill="none"><rect x="2" y="2" width="8" height="8" rx="1" '
            'stroke="{c}" stroke-width="1.1"/></svg>'),
    'restore': ('<svg viewBox="0 0 12 12" fill="none">'
                '<rect x="1.5" y="3.5" width="7" height="7" rx="1" stroke="{c}" stroke-width="1.1"/>'
                '<path d="M4 3.5V2.2h5.8v5.8H8.5" stroke="{c}" stroke-width="1.1"/></svg>'),
    'close': ('<svg viewBox="0 0 12 12"><path d="M2.4 2.4 9.6 9.6M9.6 2.4 2.4 9.6" stroke="{c}" '
              'stroke-width="1.1" stroke-linecap="round"/></svg>'),

    # ── 工具栏 ──
    'new': ('<svg viewBox="0 0 14 14"><path d="M7 2.8v8.4M2.8 7h8.4" stroke="{c}" stroke-width="1.4" '
            'stroke-linecap="round"/></svg>'),
    'open': ('<svg viewBox="0 0 14 14" fill="none"><path d="M1.6 4a1.2 1.2 0 0 1 1.2-1.2h2.4l1.4 '
             '1.6h5a1.2 1.2 0 0 1 1.2 1.2v5.6a1.2 1.2 0 0 1-1.2 1.2H2.8A1.2 1.2 0 0 1 1.6 '
             '11.2V4Z" stroke="{c}" stroke-width="1.1" stroke-linejoin="round"/></svg>'),
    'save': ('<svg viewBox="0 0 14 14" fill="none"><path d="M2.6 2h7l2.4 2.4v7.6H2.6V2Z" stroke="{c}" '
             'stroke-width="1.1" stroke-linejoin="round"/><path d="M4.8 12V8.4h4.4V12" stroke="{c}" '
             'stroke-width="1.1" stroke-linejoin="round"/><path d="M4.8 2v3h3.6V2" stroke="{c}" '
             'stroke-width="1.1" stroke-linejoin="round"/></svg>'),
    'find': ('<svg viewBox="0 0 14 14" fill="none"><circle cx="6.2" cy="6.2" r="4" stroke="{c}" '
             'stroke-width="1.2"/><path d="M9.2 9.2 12 12" stroke="{c}" stroke-width="1.2" '
             'stroke-linecap="round"/></svg>'),
    'settings': ('<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="2.2" stroke="{c}" '
                 'stroke-width="1.1"/><path d="M8 1.6v1.6M8 12.8v1.6M14.4 8h-1.6M3.2 8H1.6M12.5 '
                 '3.5l-1.1 1.1M4.6 11.4l-1.1 1.1M12.5 12.5l-1.1-1.1M4.6 4.6 3.5 3.5" stroke="{c}" '
                 'stroke-width="1.1" stroke-linecap="round"/></svg>'),

    # ── 侧栏 ──
    'panel-left-hide': ('<svg viewBox="0 0 14 14" fill="none"><path d="M8.6 3.4 5 7l3.6 3.6" '
                        'stroke="{c}" stroke-width="1.3" stroke-linecap="round" '
                        'stroke-linejoin="round"/><path d="M2.6 2.6v8.8" stroke="{c}" '
                        'stroke-width="1.3" stroke-linecap="round"/></svg>'),
    'panel-left-show': ('<svg viewBox="0 0 14 14" fill="none"><rect x="1.6" y="2.8" width="10.8" '
                        'height="8.4" rx="1.5" stroke="{c}" stroke-width="1.2"/><path d="M5.4 '
                        '2.8v8.4" stroke="{c}" stroke-width="1.2"/></svg>'),
    'panel-right-hide': ('<svg viewBox="0 0 14 14" fill="none"><path d="M5.4 3.4 9 7l-3.6 3.6" '
                         'stroke="{c}" stroke-width="1.3" stroke-linecap="round" '
                         'stroke-linejoin="round"/><path d="M11.4 2.6v8.8" stroke="{c}" '
                         'stroke-width="1.3" stroke-linecap="round"/></svg>'),
    'chevron-down': ('<svg viewBox="0 0 12 12" fill="none"><path d="M3 4.6 6 7.6l3-3" stroke="{c}" '
                     'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
    'chevron-right': ('<svg viewBox="0 0 12 12" fill="none"><path d="M4.6 3 7.6 6l-3 3" stroke="{c}" '
                      'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
    'folder': ('<svg viewBox="0 0 14 14" fill="none"><path d="M1.6 4a1.2 1.2 0 0 1 1.2-1.2h2.4l1.4 '
               '1.6h5a1.2 1.2 0 0 1 1.2 1.2v5.6a1.2 1.2 0 0 1-1.2 1.2H2.8A1.2 1.2 0 0 1 1.6 '
               '11.2V4Z" stroke="{c}" stroke-width="1.1" stroke-linejoin="round"/></svg>'),
    'file': ('<svg viewBox="0 0 14 14" fill="none"><path d="M8 1.6H4.2a1.2 1.2 0 0 0-1.2 '
             '1.2v8.4a1.2 1.2 0 0 0 1.2 1.2h5.6a1.2 1.2 0 0 0 1.2-1.2V4.6L8 1.6Z" stroke="{c}" '
             'stroke-width="1.1" stroke-linejoin="round"/><path d="M8 1.6v3h3" stroke="{c}" '
             'stroke-width="1.1" stroke-linejoin="round"/></svg>'),
    'plus': ('<svg viewBox="0 0 13 13"><path d="M6.5 2.6v7.8M2.6 6.5h7.8" stroke="{c}" '
             'stroke-width="1.3" stroke-linecap="round"/></svg>'),
    'search': ('<svg viewBox="0 0 14 14" fill="none"><circle cx="6.2" cy="6.2" r="4" stroke="{c}" '
               'stroke-width="1.2"/><path d="M9.2 9.2 12 12" stroke="{c}" stroke-width="1.2" '
               'stroke-linecap="round"/></svg>'),

    # ── Push / 同步 ──
    'push': ('<svg viewBox="0 0 16 16" fill="none"><path d="M8 13.2V3.4" stroke="{c}" '
             'stroke-width="1.7" stroke-linecap="round"/><path d="M4.2 7.2 8 3.4l3.8 3.8" '
             'stroke="{c}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
    'pull': ('<svg viewBox="0 0 16 16" fill="none"><path d="M8 2.4v8" stroke="{c}" '
             'stroke-width="1.3" stroke-linecap="round"/><path d="M4.8 7.2 8 10.4l3.2-3.2" '
             'stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
             '<path d="M2.8 13.2h10.4" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/></svg>'),
    'diff': ('<svg viewBox="0 0 16 16" fill="none"><path d="M5.4 2.2v5.2M2.8 4.8h5.2" stroke="{c}" '
             'stroke-width="1.3" stroke-linecap="round"/><path d="M9.4 11.6h4.2" stroke="{c}" '
             'stroke-width="1.3" stroke-linecap="round"/><path d="M2.6 11.6h4.2" stroke="{c}" '
             'stroke-width="1.3" stroke-linecap="round"/></svg>'),
    'check-circle': ('<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.4" '
                     'stroke="{c}" stroke-width="1.4"/><path d="M5.4 8.2 7.2 10l3.4-3.6" '
                     'stroke="{c}" stroke-width="1.4" stroke-linecap="round" '
                     'stroke-linejoin="round"/></svg>'),
    'alert-circle': ('<svg viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="7.4" '
                     'stroke="{c}" stroke-width="1.4"/><path d="M9 5.2v4.8" stroke="{c}" '
                     'stroke-width="1.5" stroke-linecap="round"/><circle cx="9" cy="12.8" r="0.9" '
                     'fill="{c}"/></svg>'),
    'branch': ('<svg viewBox="0 0 12 12" fill="none"><circle cx="3.2" cy="2.8" r="1.4" '
               'stroke="{c}"/><circle cx="3.2" cy="9.2" r="1.4" stroke="{c}"/><circle cx="8.8" '
               'cy="5.2" r="1.4" stroke="{c}"/><path d="M3.2 4.2v3.6" stroke="{c}"/><path '
               'd="M8.8 6.6v.6a2 2 0 0 1-2 2H4.6" stroke="{c}"/></svg>'),
    'link': ('<svg viewBox="0 0 16 16" fill="none"><path d="M6.2 9.8 9.8 6.2" stroke="{c}" '
             'stroke-width="1.3" stroke-linecap="round"/><path d="M7.6 4.6 8.6 3.6a2.6 2.6 0 0 1 '
             '3.7 3.7l-1 1" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/><path '
             'd="M8.4 11.4 7.4 12.4a2.6 2.6 0 0 1-3.7-3.7l1-1" stroke="{c}" stroke-width="1.3" '
             'stroke-linecap="round"/></svg>'),
    'github': ('<svg viewBox="0 0 16 16" fill="none"><path d="M8 1.2a6.8 6.8 0 0 0-2.15 13.25c.34'
               '.06.46-.15.46-.33v-1.16c-1.89.41-2.29-.91-2.29-.91-.31-.79-.76-.99-.76-.99-.62-.43'
               '.05-.42.05-.42.69.05 1.05.71 1.05.71.61 1.05 1.6.75 1.99.57.06-.44.24-.75.43-.92-1'
               '.51-.17-3.1-.76-3.1-3.36 0-.74.27-1.35.71-1.83-.07-.17-.31-.87.07-1.81 0 0 .58-.19 '
               '1.89.7a6.5 6.5 0 0 1 3.44 0c1.31-.89 1.89-.7 1.89-.7.38.94.14 1.64.07 1.81.44.48.71 '
               '1.09.71 1.83 0 2.61-1.6 3.19-3.12 3.36.25.21.47.63.47 1.27v1.88c0 .18.12.4.46.33A6.8 '
               '6.8 0 0 0 8 1.2Z" fill="{c}"/></svg>'),
    'external': ('<svg viewBox="0 0 14 14" fill="none"><path d="M6 2.8H2.8v8.4h8.4V8" stroke="{c}" '
                 'stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/><path '
                 'd="M8.4 2.8h2.8v2.8" stroke="{c}" stroke-width="1.1" stroke-linecap="round" '
                 'stroke-linejoin="round"/><path d="M11.2 2.8 7 7" stroke="{c}" stroke-width="1.1" '
                 'stroke-linecap="round"/></svg>'),
    'pencil': ('<svg viewBox="0 0 14 14" fill="none"><path d="M9.6 2.2 11.8 4.4 5 11.2H2.8V9L9.6 '
               '2.2Z" stroke="{c}" stroke-width="1.1" stroke-linejoin="round"/></svg>'),
    'minus-circle': ('<svg viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.4" '
                     'stroke="{c}" stroke-width="1.1"/><path d="M4.6 7h4.8" stroke="{c}" '
                     'stroke-width="1.2" stroke-linecap="round"/></svg>'),
    'text-file': ('<svg viewBox="0 0 40 40" fill="none"><rect x="8" y="7" width="24" height="26" '
                  'rx="2" stroke="{c}" stroke-width="1.6"/><path d="M14 15h12M14 20h12M14 25h7" '
                  'stroke="{c}" stroke-width="1.6" stroke-linecap="round"/></svg>'),
    'doc-file': ('<svg viewBox="0 0 40 40" fill="none"><path d="M23 7H12a2 2 0 0 0-2 2v22a2 2 0 0 '
                 '0 2 2h16a2 2 0 0 0 2-2V14l-7-7Z" stroke="{c}" stroke-width="1.6" '
                 'stroke-linejoin="round"/><path d="M23 7v7h7" stroke="{c}" stroke-width="1.6" '
                 'stroke-linejoin="round"/></svg>'),

    # ── 认证对话框 ──
    'copy': ('<svg viewBox="0 0 14 14" fill="none">'
             '<rect x="1.4" y="1.4" width="8.2" height="8.2" rx="1.8" stroke="{c}" '
             'stroke-width="1.1"/>'
             '<path d="M4.6 12.6h6.4a1.6 1.6 0 0 0 1.6-1.6V4.6" stroke="{c}" stroke-width="1.1" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>'),
    'refresh': ('<svg viewBox="0 0 14 14" fill="none">'
                '<path d="M12 7a5 5 0 1 1-1.6-3.7" stroke="{c}" stroke-width="1.3" '
                'stroke-linecap="round"/>'
                '<path d="M12.2 2.2v3.4h-3.4" stroke="{c}" stroke-width="1.3" '
                'stroke-linecap="round" stroke-linejoin="round"/></svg>'),
}


def icon(name: str, color: str = C_BODY, size: int = 16,
         second: str | None = None, dpr: float = 2.0) -> QIcon:
    """按名字生成 QIcon。``second`` 用于双色图标（如应用标识的第二色）。"""
    tpl = _TEMPLATES.get(name)
    if tpl is None:
        return QIcon()
    svg = tpl.replace('{c}', color)
    svg = svg.replace('{c2}', second or color)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    painter = QPainter(px)
    renderer.render(painter)
    painter.end()
    px.setDevicePixelRatio(dpr)
    return QIcon(px)


def app_icon() -> QIcon:
    """应用图标（标题栏与任务栏共用）。"""
    return icon('app', C_SECOND, 16, second=C_PRIMARY)
