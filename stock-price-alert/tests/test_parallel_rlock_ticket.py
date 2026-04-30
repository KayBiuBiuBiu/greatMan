"""模拟 process_watch 多线程下 state 互斥：RLock 保证 ticket 不丢。"""

from __future__ import annotations

import threading


def test_rlock_serializes_critical_section() -> None:
    state: dict[str, int] = {"n": 0}
    lock = threading.RLock()

    def worker() -> None:
        for _ in range(500):
            with lock:
                v = state["n"]
                state["n"] = v + 1

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert state["n"] == 2000
