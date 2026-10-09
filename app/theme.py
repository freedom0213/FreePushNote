# -*- coding: utf-8 -*-
"""设计 token 与全局样式（唯一真源）。

组件里一律引用这里的常量，不要把颜色 / 字号 / 间距写死在控件里。
数值来源：

* Ardot 主设计稿 v3 —— fileId ``733847576651907``（11 块画板）
* Ardot 交互补充稿   —— fileId ``733854451061601``（8 块）
* ``D:/Vibe-coding/FreePushNote/FreePushNote-项目现状.md``

主题**固定深色**，不跟随系统。
"""
from __future__ import annotations

# ────────────────────────────── 颜色 ──────────────────────────────
# 三层色阶（靠背景分层，少画线）
BG_APP = '#1E1E1E'          # 编辑区 / 窗口底色
BG_PANEL = '#252526'        # 侧栏 / 卡片 / 状态栏
BG_BAR = '#323233'          # 标题栏 / 工具栏
BG_CARD = '#2D2D30'         # 卡片（比侧栏更亮一档）
BG_INPUT = '#1E1E1E'        # 输入框

BG_HOVER = '#2A2D2E'        # 悬停
BG_ACTIVE = '#37373D'       # 按下
BG_SELECTED = '#264F78'     # 选中（列表项）
BG_SELECTED_SOFT = '#2F4A5E'  # 选中（菜单项）

BORDER = '#3C3C3C'          # 常规边框
BORDER_STRONG = '#4A4A4C'
BORDER_SOFT = '#2A2A2A'     # 同色相邻时才用的极淡分隔

# 文字四级
TEXT_STRONG = '#EDEDED'     # 标题 / 窗口标题
TEXT_PRIMARY = '#D4D4D4'    # 正文 / 主要文本
TEXT_BODY = '#C8C8C8'       # 控件文本
TEXT_SECOND = '#9D9D9D'     # 次要
TEXT_MUTED = '#8C8C8C'      # 辅助
TEXT_WEAK = '#6A6A6A'       # 弱化（分组名、提示）
TEXT_FAINT = '#5A5F63'      # 极弱（快捷键、时间）
TEXT_GHOST = '#4A4A4C'      # 禁用

# 语义色
PRIMARY = '#0E639C'         # 主色（Push 按钮）
PRIMARY_HOVER = '#1177BB'
PRIMARY_PRESSED = '#0B5384'
PRIMARY_SOFT = '#2A4256'    # 推送中（暗蓝）
SUCCESS = '#89D185'         # 已同步 / 成功
WARNING = '#CCA700'         # 待推送 / 提示
ERROR = '#F48771'           # 失败
LINK = '#1177BB'

# 半透明底（胶囊 / 提示条）
def alpha(hex_color: str, a: float) -> str:
    """把 #RRGGBB 转成 rgba(...) 字符串，用于 QSS。"""
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f'rgba({r}, {g}, {b}, {a:.2f})'


# ────────────────────────────── 尺寸 ──────────────────────────────
WIN_W, WIN_H = 1200, 760
WIN_MIN_W, WIN_MIN_H = 900, 560

TITLEBAR_H = 34
TOOLBAR_H = 38
STATUSBAR_H = 24
SIDEBAR_W = 200
SIDEBAR_RAIL_W = 40        # 左栏收起后的窄条（只需一个展开按钮）
PANEL_W = 300
PANEL_RAIL_W = 48          # 右栏收起后的窄条（要放状态灯 + Push + 设置，所以宽一点）

# 间距栅格：一律用 4 的倍数
SP1, SP2, SP3, SP4, SP5, SP6, SP8 = 4, 8, 12, 16, 20, 24, 32

# 圆角三级
RADIUS_BTN = 4             # 按钮 / 输入框
RADIUS_CARD = 8            # 卡片 / 弹窗
RADIUS_WIN = 11            # 窗口本体

# ────────────────────────────── 字体 ──────────────────────────────
# 界面字体：非等宽
UI_STACK = '"Microsoft YaHei UI", "Segoe UI", "Noto Sans SC", sans-serif'
# 等宽：正文与数字。Sarasa 是等宽 CJK，中文与拉丁能对齐；Cascadia 是 Win11 自带
MONO_STACK = ('"Sarasa Mono SC", "Sarasa Gothic SC", "Cascadia Mono", '
              '"Consolas", monospace')

# 字号
FS_TITLE = 15              # 区块标题 / 窗口标题
FS_BODY = 16               # 编辑区正文默认字号（15 用户实测偏小，提到 16）
FS_BODY_MIN = 12           # Ctrl+滚轮下限：再小就看不清了
FS_BODY_MAX = 32           # 上限：再大一行放不下几个字
LH_BODY = 26               # 基准行高（对应字号 15），其余字号按比例换算
FS_UI = 12.5               # 界面控件
FS_SMALL = 11.5            # 次要信息
FS_TINY = 11               # 辅助
FS_LABEL = 10.5            # 极小的标签（哈希、时间）

# 行高 / 字号比例（15 → 26），缩放时按它联动，保证行距观感一致
LINE_HEIGHT_RATIO = LH_BODY / 15.0

# ── 行号栏（刻意弱化：小字 + 极淡色 + 无背景条） ──
GUTTER_FS_DELTA = -4       # 行号字号 = 正文字号 + 这个（负数）
GUTTER_FS_MIN = 9          # 行号字号下限
GUTTER_FS_MAX = 14         # 行号字号上限：正文放到 32 时行号也不超过这个
GUTTER_FG = '#454545'      # 常态：几乎融进背景
GUTTER_FG_CURRENT = '#6A6A6A'  # 当前行：稍亮但仍不抢眼
GUTTER_WRAP_MARK = '#4A4A4C'   # 软换行续行的标记点
GUTTER_PAD_L = 12          # 左边距
GUTTER_PAD_R = 10          # 与正文的间距

# 编辑区左右内边距（正文顶格，不做居中）
EDITOR_PAD_LEFT = 28
EDITOR_PAD_TOP = 28


# ────────────────────────────── QSS ──────────────────────────────
def qss() -> str:
    """全局样式表。控件级的细节仍可在各自组件里补充。"""
    return f"""
    /* ⚠️ 这里**不能**写 font-family / font-size。
       Qt 的 QSS 一旦匹配到字体属性，就会接管该控件的字体，setFont() 直接被丢掉 ——
       结果是编辑区既拿不到等宽字体、也没法用 Ctrl+滚轮 改字号
       （探针能读到新字号，画面却纹丝不动，就是踩了这个）。
       默认字体统一由 QApplication.setFont() 提供，见 app/main.py。 */
    * {{
        color: {TEXT_BODY};
        outline: none;
    }}

    QWidget#Root {{
        background: {BG_APP};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_WIN}px;
    }}
    /* 最大化时贴边，圆角要让位给屏幕边缘 */
    QWidget#Root[maximized="true"] {{
        border-radius: 0;
        border: none;
    }}

    /* ── 标题栏 / 工具栏 ─────────────────────────── */
    QFrame#TitleBar, QFrame#ToolBar {{
        background: {BG_BAR};
    }}
    QFrame#TitleBar {{
        border-bottom: 1px solid {BORDER};
        border-top-left-radius: {RADIUS_WIN}px;
        border-top-right-radius: {RADIUS_WIN}px;
    }}
    QFrame#ToolBar {{
        border-bottom: 1px solid {BORDER};
    }}
    QLabel#TitleFileName {{
        color: {TEXT_PRIMARY};
        font-size: {FS_UI}px;
    }}
    QLabel#AppName {{
        color: {TEXT_MUTED};
        font-size: {FS_TINY}px;
    }}

    /* 窗口控制按钮 */
    QToolButton#WinBtn {{
        border: none;
        background: transparent;
        border-radius: 0;
    }}
    QToolButton#WinBtn:hover {{
        background: {alpha('#FFFFFF', 0.08)};
    }}
    QToolButton#WinBtn:pressed {{
        background: {alpha('#FFFFFF', 0.14)};
    }}
    QToolButton#WinBtnClose:hover {{
        background: #C42B1C;
    }}

    /* 工具栏普通按钮 */
    QToolButton#ToolBtn {{
        border: none;
        background: transparent;
        border-radius: {RADIUS_BTN}px;
        padding: 4px 10px;
        color: {TEXT_BODY};
    }}
    QToolButton#ToolBtn:hover {{
        background: {alpha('#FFFFFF', 0.07)};
    }}
    QToolButton#ToolBtn:pressed {{
        background: {alpha('#FFFFFF', 0.12)};
    }}
    QToolButton#ToolBtn:disabled {{
        color: {TEXT_GHOST};
    }}

    /* ── 左侧栏 ─────────────────────────────────── */
    QFrame#Sidebar {{
        background: {BG_PANEL};
        border-right: 1px solid {BORDER};
    }}
    QLabel#GroupHeader {{
        color: {TEXT_WEAK};
        font-size: {FS_TINY}px;
        font-weight: 600;
    }}
    QListWidget#NoteTree, QTreeWidget#NoteTree {{
        background: transparent;
        border: none;
        padding: 0;
        outline: none;
    }}
    QListWidget#NoteTree::item, QTreeWidget#NoteTree::item {{
        height: 28px;
        border-radius: {RADIUS_BTN}px;
        color: {TEXT_SECOND};
    }}
    QListWidget#NoteTree::item {{
        padding-left: 8px;
    }}
    QListWidget#NoteTree::item:hover, QTreeWidget#NoteTree::item:hover {{
        background: {BG_HOVER};
    }}
    QListWidget#NoteTree::item:selected, QTreeWidget#NoteTree::item:selected {{
        background: {BG_SELECTED};
        color: {TEXT_STRONG};
    }}
    /* 展开箭头用自定义图标，去掉 Qt 自带的分支指示器 */
    QTreeWidget#NoteTree::branch {{
        background: transparent;
        border-image: none;
        image: none;
    }}
    QTreeWidget#NoteTree {{
        qproperty-indentation: 14;
        qproperty-rootIsDecorated: false;
    }}

    /* ── 编辑区 ─────────────────────────────────── */
    QPlainTextEdit#Editor {{
        background: {BG_APP};
        border: none;
        color: {TEXT_PRIMARY};
        selection-background-color: {BG_SELECTED};
    }}

    /* ── 右侧栏 ─────────────────────────────────── */
    QFrame#PushPanel {{
        background: {BG_PANEL};
        border-left: 1px solid {BORDER};
    }}
    QFrame#PanelHeader {{
        border-bottom: 1px solid {BORDER};
    }}
    QFrame#Card {{
        background: {BG_CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#CardError {{
        background: {BG_CARD};
        border: 1px solid #4A3A3A;
        border-radius: {RADIUS_CARD}px;
    }}

    /* Push 主按钮 */
    QPushButton#PushButton {{
        background: {PRIMARY};
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        font-size: {FS_UI}px;
        font-weight: 600;
    }}
    QPushButton#PushButton:hover  {{ background: {PRIMARY_HOVER}; }}
    QPushButton#PushButton:pressed {{ background: {PRIMARY_PRESSED}; }}
    QPushButton#PushButton:disabled {{
        background: #3A3A3C;
        color: {TEXT_MUTED};
        border: 1px solid {BORDER_STRONG};
    }}
    /* 三种状态用动态属性切换 */
    QPushButton#PushButton[state="running"] {{
        background: {PRIMARY_SOFT};
        color: #A6BDCD;
    }}
    QPushButton#PushButton[state="success"] {{
        background: {SUCCESS};
        color: {BG_APP};
    }}
    /* 已是最新：保持可点（远端落后时还能重推），但视觉压灰不诱导点击 */
    QPushButton#PushButton[state="uptodate"] {{
        background: #3A3A3C;
        color: {TEXT_MUTED};
        border: 1px solid {BORDER_STRONG};
    }}

    /* 次要按钮 */
    QPushButton#GhostButton {{
        background: {BG_CARD};
        color: {TEXT_BODY};
        border: 1px solid {BORDER};
        border-radius: 6px;
        font-size: {FS_SMALL}px;
    }}
    QPushButton#GhostButton:hover {{
        background: {BG_HOVER};
        border-color: {BORDER_STRONG};
    }}

    /* ── 状态栏 ─────────────────────────────────── */
    QFrame#StatusBar {{
        background: {BG_PANEL};
        border-top: 1px solid {BORDER};
    }}
    QLabel#StatusText {{
        color: {TEXT_MUTED};
        font-size: {FS_SMALL}px;
    }}
    QLabel#StatusTextMono {{
        color: {TEXT_MUTED};
        font-size: {FS_SMALL}px;
        font-family: {MONO_STACK};
    }}
    QLabel#StatusFaint {{
        color: {TEXT_WEAK};
        font-size: {FS_SMALL}px;
    }}

    /* ── 滚动条（8px 细样式，无箭头） ─────────────── */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_STRONG};
        border-radius: 4px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #5A5A5C;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; border: none; background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER_STRONG};
        border-radius: 4px;
        min-width: 32px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; border: none; background: none;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* ── 提示 / 菜单 ─────────────────────────────── */
    QToolTip {{
        background: {BG_CARD};
        color: {TEXT_BODY};
        border: 1px solid {BORDER};
        padding: 4px 8px;
    }}
    QMenu {{
        background: {BG_CARD};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 6px 18px 6px 10px;
        border-radius: {RADIUS_BTN}px;
        color: {TEXT_BODY};
    }}
    QMenu::item:selected {{
        background: {BG_SELECTED_SOFT};
        color: {TEXT_STRONG};
    }}
    QMenu::item:disabled {{
        color: {TEXT_GHOST};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 2px;
    }}

    /* ── 对话框（认证 / 纳管等） ─────────────────── */
    QFrame#DialogCard {{
        background: {BG_PANEL};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#DialogHeader {{
        border-bottom: 1px solid {BORDER};
    }}
    /* 验证码：整个界面上唯一允许「大而显眼」的文字 */
    QLabel#AuthCode {{
        background: {BG_INPUT};
        border: 1px solid {BORDER_STRONG};
        border-radius: 6px;
        color: {TEXT_STRONG};
        font-family: {MONO_STACK};
        font-size: 22px;
        font-weight: 600;
    }}
    QFrame#AuthStep {{
        background: {BG_CARD};
        border: 1px solid {BORDER};
        border-radius: 6px;
    }}
    QFrame#AuthError {{
        background: {alpha(ERROR, 0.10)};
        border: 1px solid #4A3A3A;
        border-radius: 6px;
    }}
    QPushButton#PrimaryButton {{
        background: {PRIMARY};
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        font-size: {FS_UI}px;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover   {{ background: {PRIMARY_HOVER}; }}
    QPushButton#PrimaryButton:pressed {{ background: {PRIMARY_PRESSED}; }}
    QPushButton#PrimaryButton:disabled {{
        background: #3A3A3C;
        color: {TEXT_MUTED};
        border: 1px solid {BORDER_STRONG};
    }}
    QPushButton#DialogButton {{
        background: {BG_CARD};
        color: {TEXT_BODY};
        border: 1px solid {BORDER};
        border-radius: 6px;
        font-size: {FS_SMALL}px;
        font-weight: 600;
    }}
    QPushButton#DialogButton:hover {{
        background: {BG_HOVER};
        border-color: {BORDER_STRONG};
    }}
    /* 退出登录按钮：描边红，不是实心红 —— 操作是可逆的（重新授权就回来），
       不必做成需要「二次确认再确认」的恐吓样式 */
    QPushButton#DangerButton {{
        background: transparent;
        color: {ERROR};
        border: 1px solid {alpha(ERROR, 0.55)};
        border-radius: 6px;
        font-size: {FS_SMALL}px;
        font-weight: 600;
    }}
    QPushButton#DangerButton:hover {{
        background: {alpha(ERROR, 0.12)};
        border-color: {ERROR};
    }}

    /* ── 编辑器内嵌查找条（Ctrl+F） ─────────────── */
    QFrame#FindBar {{
        background: {BG_PANEL};
        border-bottom: 1px solid {BORDER};
    }}
    QLineEdit#FindInput {{
        background: transparent;
        border: none;
        color: {TEXT_PRIMARY};
        font-size: {FS_UI}px;
    }}
    QToolButton#LinkButton {{
        border: none;
        background: transparent;
        color: {TEXT_WEAK};
        font-size: {FS_TINY}px;
    }}
    QToolButton#LinkButton:hover {{ color: {TEXT_SECOND}; }}

    /* 提示条（纳管 / 推送对话框共用） */
    QFrame#NoteWarn {{
        background: {alpha(WARNING, 0.12)};
        border: 1px solid #4A4030;
        border-radius: 6px;
    }}
    QFrame#NoteInfo {{
        background: {alpha(PRIMARY, 0.12)};
        border: 1px solid #2A4256;
        border-radius: 6px;
    }}

    /* 输入框 */
    QLineEdit#Input {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BTN}px;
        padding: 0 10px;
        color: {TEXT_PRIMARY};
    }}
    QLineEdit#Input:focus {{
        border-color: {PRIMARY_HOVER};
    }}

    /* 可滚动的文件清单 */
    QScrollArea#ScrollHost {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 6px;
    }}
    QScrollArea#ScrollHost > QWidget > QWidget {{
        background: transparent;
    }}
    """


def editor_font():
    """编辑区正文用字体（调用方需要 QFont 时用）——延迟导入，避免无 GUI 环境报错。"""
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(['Sarasa Mono SC', 'Sarasa Gothic SC', 'Cascadia Mono', 'Consolas'])
    f.setStyleStrategy(QFont.PreferAntialias)
    f.setPixelSize(FS_BODY)
    return f
