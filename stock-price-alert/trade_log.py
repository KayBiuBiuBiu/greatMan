"""策略 / 风控信号落盘（最多保留约 200 条）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def log_signal(
    name: str,
    code: str,
    signal: str,
    price: float,
    *,
    base_dir: Path | None = None,
    filename: str = "trade_log.json",
) -> None:
    base = base_dir or Path(".")
    path = base / filename
    log: list[dict[str, object]] = []
    if path.exists():
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(log, list):
                log = []
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(
        {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "code": code,
            "price": round(price, 4),
            "signal": signal,
        }
    )
    try:
        path.write_text(
            json.dumps(log[-200:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
