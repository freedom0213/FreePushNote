# -*- coding: utf-8 -*-
"""崩溃现场记录：把「它崩了」变成可查的证据。

**为什么需要它**（2026-10-13 真机崩溃换来的教训）：用 ``pythonw`` 启动**没有控制台**，
Python 与 Qt 的报错全被丢掉；而 Windows 上进程被 ``abort()`` 带走时，
异常代码是 ``0xC0000409``（``FAST_FAIL_FATAL_APP_EXIT``）—— 这种硬崩溃
**根本不走 Python 的异常钩子**，连 ``sys.excepthook`` 都不会被调用。
结果就是：窗口突然消失，日志为空，只能靠猜。

这里做四件事，都只在 :func:`enable` 之后生效（自测不受影响）：

1. 把 **stdout / stderr 的底层文件描述符**重定向到日志文件。
   只换 ``sys.stderr`` 不够 —— PySide6 是**直接往 fd 2 写**的。
2. 装 ``threading.excepthook``（普通线程里的异常默认只打印，容易漏）。
3. ``faulthandler``：**abort / 访问违例时 dump Python 栈**，
   这是唯一能从硬崩溃里拿到线索的手段。
4. :func:`note`：把「走到哪一步」写进同一个文件 —— 硬崩溃时**最后一行就是现场**。
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import date, datetime

_ENABLED = False
_LOGFILE = None
_LOCK = threading.Lock()


def log_path():
    """当天的会话日志路径（目录必要时创建）。"""
    from core import config
    d = config.CONFIG_DIR / 'logs'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'session-{date.today():%Y%m%d}.log'


def enable(*, redirect: bool = True, install_handlers: bool = True) -> str | None:
    """开启现场记录，返回日志路径；失败返回 ``None``。

    绝不因为记日志失败而让程序起不来 —— 所以整段都兜住了异常。

    ``redirect=False`` / ``install_handlers=False`` 是给自测用的：
    测试不该把 stdout 抢走（否则整个套件的输出会消失，看起来像挂死）。
    """
    global _ENABLED, _LOGFILE
    if _ENABLED:
        return str(_LOGFILE.name) if _LOGFILE is not None else None
    try:
        path = log_path()
        # 行缓冲：崩溃那一刻已经写下去的行必须真的在磁盘上
        _LOGFILE = open(path, 'a', encoding='utf-8', buffering=1)
    except OSError:
        return None
    _ENABLED = True

    if redirect:
        _redirect_fds(_LOGFILE)
        sys.stdout = _LOGFILE
        sys.stderr = _LOGFILE
    if install_handlers:
        sys.excepthook = _excepthook
        threading.excepthook = _thread_excepthook
        try:
            import faulthandler
            # 硬崩溃（abort / 访问违例）时 dump 所有线程的 Python 栈
            faulthandler.enable(file=_LOGFILE, all_threads=True)
        except Exception:      # noqa: BLE001
            pass
    note(f'--- 会话开始 pid={os.getpid()} ---')
    return str(path)


def disable() -> None:
    """关掉记录并还原（自测用，保证不影响后续输出）。"""
    global _ENABLED, _LOGFILE
    _ENABLED = False
    if _LOGFILE is None:
        return
    try:
        _LOGFILE.flush()
        _LOGFILE.close()
    except OSError:
        pass
    _LOGFILE = None
    sys.excepthook = sys.__excepthook__
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__


def note(msg: str) -> None:
    """记一行「我走到这里了」。未启用时是**空操作**。"""
    if not _ENABLED or _LOGFILE is None:
        return
    try:
        with _LOCK:
            _LOGFILE.write(f'{datetime.now():%H:%M:%S.%f}  {msg}\n')
            _LOGFILE.flush()
    except Exception:          # noqa: BLE001 - 记日志本身绝不能把程序带崩
        pass


def _redirect_fds(fh) -> None:
    try:
        os.dup2(fh.fileno(), 1)
        os.dup2(fh.fileno(), 2)
    except OSError:
        pass


def _excepthook(exc_type, exc, tb) -> None:
    note('未捕获异常：' + ''.join(traceback.format_exception(exc_type, exc, tb)))
    try:
        sys.__excepthook__(exc_type, exc, tb)
    except Exception:          # noqa: BLE001
        pass


def _thread_excepthook(args) -> None:
    note('线程内未捕获异常（{}）：'.format(getattr(args.thread, 'name', '?'))
         + ''.join(traceback.format_exception(args.exc_type, args.exc_value,
                                              args.exc_traceback)))
