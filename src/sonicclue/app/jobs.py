"""Background jobs with cancellation (docs/specs/03-system-architecture.md section 6).

A small ThreadPoolExecutor (2 workers). numpy/scipy release the GIL in heavy
kernels, so analysis threads do not freeze the GUI. Each job receives a
CancelToken and checks it at defined cancellation points (between channels
and between pipeline stages). The GUI receives completion through the
callbacks it registers; it marshals them onto the Qt thread itself.
Shutdown: ``shutdown()`` cancels pending jobs and waits for running jobs to
reach a cancellation point.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Callable


class CancelToken:
    def __init__(self):
        self._evt = threading.Event()

    def cancel(self) -> None:
        self._evt.set()

    def __call__(self) -> bool:
        return self._evt.is_set()


class JobRunner:
    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sc-job")
        self._tokens: dict[Future, CancelToken] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable, *args, **kwargs) -> tuple[Future, CancelToken]:
        tok = CancelToken()
        fut = self._pool.submit(fn, *args, cancel=tok, **kwargs)
        with self._lock:
            self._tokens[fut] = tok
        fut.add_done_callback(self._forget)
        return fut, tok

    def _forget(self, fut: Future) -> None:
        with self._lock:
            self._tokens.pop(fut, None)

    def cancel_all(self, timeout: float | None = 30.0) -> None:
        """Cancel every pending/running job and wait for them to stop (the pool stays usable).
        Must not be called from a job thread."""
        with self._lock:
            items = list(self._tokens.items())
        for _, tok in items:
            tok.cancel()
        wait([f for f, _ in items], timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            for t in list(self._tokens.values()):
                t.cancel()
        self._pool.shutdown(wait=wait, cancel_futures=True)
