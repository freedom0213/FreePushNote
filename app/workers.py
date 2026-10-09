# -*- coding: utf-8 -*-
"""耗时操作的后台线程。

为什么要有线程：两类操作都不该压在界面线程上 ——

* **推送要联网**，而且失败会重试（默认 3 次 × 5 秒间隔），最坏卡十几秒；
* **整理工作区**（同步文件 → 生成站点 → ``git add``）不联网，但要跑十来个
  git 子进程、读写成堆文件，实测也要两三秒，放在界面线程上就是「点了没反应」。

两者都放这里。线程引用必须集中持有，否则 ``QThread`` 被 GC 掉会导致进程
直接崩溃（Qt 的老坑）。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core import pipeline

#: 运行中的线程。结束时自己摘掉；即使窗口已关闭也能安全跑完。
_LIVE: set[QThread] = set()


class StageWorker(QThread):
    """执行 :func:`core.pipeline.stage_group`（整理到工作区，不提交）。"""

    done = Signal(object)      # pipeline.StageResult

    def __init__(self, group: dict, *, account: dict | None = None,
                 on_log=None) -> None:
        super().__init__()
        self._group = group
        self._account = account
        self._on_log = on_log

    def run(self) -> None:  # noqa: D102
        try:
            result = pipeline.stage_group(self._group, account=self._account,
                                          on_log=self._on_log)
        except Exception as exc:  # noqa: BLE001 - 兜底：绝不让异常把线程带崩
            result = pipeline.StageResult(
                reason=pipeline.REASON_GIT_ERROR,
                message='准备这次要提交的内容时出错了。', detail=repr(exc))
        self.done.emit(result)


class PushWorker(QThread):
    """执行 :func:`core.pipeline.finalize_push`（提交 + 推送）。"""

    done = Signal(object)      # pipeline.PushResult

    def __init__(self, group: dict, staged, *, message: str, keep: list[str] | None,
                 token: str, retries: int = 3) -> None:
        super().__init__()
        self._group = group
        self._staged = staged
        self._message = message
        self._keep = keep
        self._token = token
        self._retries = retries

    def run(self) -> None:  # noqa: D102
        try:
            result = pipeline.finalize_push(
                self._group, self._staged, message=self._message,
                token=self._token, keep=self._keep, retries=self._retries)
        except Exception as exc:  # noqa: BLE001 - 兜底：绝不让异常把线程带崩
            result = pipeline.PushResult(
                reason=pipeline.REASON_PUSH_FAILED,
                message='推送过程中出现了意外错误。', detail=repr(exc))
        self.done.emit(result)


def start_worker(worker: QThread) -> QThread:
    """启动并持有引用（调用方不必自己管 GC）。"""
    _LIVE.add(worker)
    worker.finished.connect(lambda w=worker: _LIVE.discard(w))
    worker.start()
    return worker
