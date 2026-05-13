"""终端持仓类命令落盘（hold / buy / add / reduce / sell / pause 等），供每日总结等统计「真实操作意图」。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def log_position_cli(
    kind: str,
    code: str,
    *,
    base_dir: Path | None = None,
    filename: str = "data/position_cli_log.json",
    name: str = "",
    hold_shares: int | None = None,
    cost_price: float | None = None,
    removed_rows: int | None = None,
    note: str = "",
) -> None:
    """
    kind:
      - hold: hold <代码> <股数> <成本> 写入 config（台账 hold_add）
      - buy / add / hold（四参数）: 记仓后收束当日买入策略提示
      - reduce / sell_partial: 减仓
      - sell_clear: sell <代码> 清仓并删 config
      - unhold: 同 sell 清仓路径
      - pause: pause <代码> 仅暂停监控（未删 config）
      - hold_watch: hold <代码> 仅入监控池
    """
    base = base_dir or Path(".")
    path = base / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                log = raw
        except (json.JSONDecodeError, OSError):
            log = []
    c = str(code or "").strip()
    if c.isdigit() and len(c) <= 6:
        c = c.zfill(6)
    rec: dict[str, Any] = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": str(kind or "").strip().lower(),
        "code": c,
        "name": str(name or "").strip(),
    }
    if hold_shares is not None:
        rec["hold_shares"] = int(hold_shares)
    if cost_price is not None:
        rec["cost_price"] = round(float(cost_price), 4)
    if removed_rows is not None:
        rec["removed_rows"] = int(removed_rows)
    if str(note or "").strip():
        rec["note"] = str(note).strip()[:200]
    log.append(rec)
    try:
        path.write_text(
            json.dumps(log[-400:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
