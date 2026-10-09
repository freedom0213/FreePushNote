# -*- coding: utf-8 -*-
"""耗时操作的后台线程。

为什么要线程：推送要联网，而且失败会重试（默认 3 次 × 5 秒间隔），
最坏情况能卡十几秒。放在界面线程上，窗口会整块白掉 —— 用户以为软件死了。

线程引用必须集中持有，否则 QThread 被 GC 掉会导致进程崩溃（Qt 的老坑）。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core import pipeline

#: 运行中的线程。结束时自己摘掉；即使窗口已关闭也能安全跑完。
_LIVE: set['PushWorker'] = set()


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


def start_push_worker(worker: PushWorker) -> PushWorker:
    """启动并持有引用（调用方不必自己管 GC）。"""
    _LIVE.add(worker)
    worker.finished.connect(lambda w=worker: _LIVE.discard(w))
    worker.start()
    return worker
