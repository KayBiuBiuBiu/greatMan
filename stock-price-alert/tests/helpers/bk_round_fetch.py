"""
与 run_alert._fetch_watch_item_pack 中「同轮 BK K 线」逻辑一致，供并发测试复用。
若主流程该段变更，请同步此函数。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from quote_eastmoney import normalize_bk_code


def fetch_sector_kline_once_per_round(
    sector_bk_res: str,
    *,
    ut: str,
    round_bk_kline: dict[str, dict[str, Any]],
    bk_round_lock: threading.Lock,
    fetcher: Callable[[str, str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    bk_key = normalize_bk_code(sector_bk_res)
    with bk_round_lock:
        skl2 = round_bk_kline.get(bk_key)
        if skl2 is None:
            skl2 = fetcher(sector_bk_res, ut)
            if skl2:
                round_bk_kline[bk_key] = skl2
    return skl2
