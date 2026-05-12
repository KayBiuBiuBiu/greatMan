"""同轮 BK K 线只 fetch 一次（与 run_alert 锁 + dict 语义一致）。"""

from __future__ import annotations

import threading

from helpers.bk_round_fetch import fetch_sector_kline_once_per_round


def test_concurrent_same_bk_single_fetch() -> None:
    round_bk: dict[str, dict] = {}
    lock = threading.Lock()
    calls: list[str] = []

    def fetcher(bk: str, ut: str) -> dict:
        calls.append(bk)
        return {"closes": [1.0] * 45, "opens": [1.0] * 45}

    def worker() -> None:
        fetch_sector_kline_once_per_round(
            "801780.SI",
            ut="ea",
            round_bk_kline=round_bk,
            bk_round_lock=lock,
            fetcher=fetcher,
        )

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(calls) == 1
    assert len(round_bk) == 1
