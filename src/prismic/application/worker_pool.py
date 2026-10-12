"""A minimal, GUI-framework-agnostic background worker pool.

Wraps `concurrent.futures.ThreadPoolExecutor` rather than Qt's own
`QThreadPool`, so the application layer stays free of a Qt dependency per
the architecture's layer boundaries (Qt is a UI-layer mechanism). Phase 5
marshals a future's result back onto the Qt GUI thread (e.g. via a queued
signal) when it wires this into the UI.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ParamSpec, TypeVar

from prismic.context import ClosableContext

_P = ParamSpec("_P")
_T = TypeVar("_T")


class WorkerPool(ClosableContext):
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="prismic-worker"
        )

    def submit(self, fn: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> Future[_T]:
        return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def close(self) -> None:
        self.shutdown()
