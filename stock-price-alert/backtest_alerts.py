#!/usr/bin/env python3
"""根据本地日 K 库为 alert_events 补算 T+1/3/5 收益与 bearish hit，并输出汇总。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alert_log_store import evaluate_row
from kline_store import init_schema, open_store_connection
from run_alert import merge_full_config


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def run_eval(
    cfg: dict[str, Any],
    *,
    root: Path,
    since: str | None,
    force: bool,
    limit: int | None,
) -> dict[str, Any]:
    from alert_log_store import resolve_alert_db_path

    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None:
        raise SystemExit("请在配置中启用 alert_log.enabled。")
    al = cfg.get("alert_log") or {}
    thresholds = {
        "bearish_hit_threshold_pct_1d": float(
            al.get("bearish_hit_threshold_pct_1d", -2.0)
        ),
        "bearish_hit_threshold_pct_3d": float(
            al.get("bearish_hit_threshold_pct_3d", -2.5)
        ),
        "bearish_hit_threshold_pct_5d": float(
            al.get("bearish_hit_threshold_pct_5d", -3.0)
        ),
    }
    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        q = "SELECT * FROM alert_events WHERE 1=1"
        params: list[Any] = []
        if not force:
            q += " AND eval_status = 'pending'"
        if since:
            q += " AND anchor_trade_date >= ?"
            params.append(since[:10])
        q += " ORDER BY id ASC"
        if limit is not None and limit > 0:
            q += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(q, params).fetchall()
        now_iso = datetime.now().isoformat(timespec="seconds")
        updated = 0
        for row in rows:
            r1, r3, r5, hit = evaluate_row(conn, row, thresholds)
            conn.execute(
                """
                UPDATE alert_events SET
                    ret_1d = ?, ret_3d = ?, ret_5d = ?,
                    hit = ?, eval_status = 'done', evaluated_iso = ?
                WHERE id = ?
                """,
                (r1, r3, r5, hit, now_iso, int(row["id"])),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()

    conn2 = open_store_connection(db_path)
    try:
        summary_rows = conn2.execute(
            """
            SELECT alert_type,
                   COUNT(*) AS n,
                   SUM(CASE WHEN hit IS NOT NULL THEN 1 ELSE 0 END) AS n_hit_scored,
                   SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) AS n_hit,
                   AVG(ret_1d) AS avg_r1,
                   AVG(ret_3d) AS avg_r3,
                   AVG(ret_5d) AS avg_r5
            FROM alert_events
            WHERE eval_status = 'done'
            GROUP BY alert_type
            ORDER BY alert_type
            """
        ).fetchall()
    finally:
        conn2.close()

    by_type: dict[str, dict[str, Any]] = {}
    for r in summary_rows:
        t = str(r["alert_type"])
        n = int(r["n"] or 0)
        n_scored = int(r["n_hit_scored"] or 0)
        n_hit = int(r["n_hit"] or 0)
        by_type[t] = {
            "n": n,
            "n_hit_scored": n_scored,
            "hit_rate": (n_hit / n_scored) if n_scored else None,
            "avg_ret_1d": r["avg_r1"],
            "avg_ret_3d": r["avg_r3"],
            "avg_ret_5d": r["avg_r5"],
        }
    return {"updated_rows": updated, "by_alert_type": by_type, "db_path": str(db_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description="预警事件回测：补算收益与 bearish 命中")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--since",
        type=str,
        default=None,
        help="只处理 anchor_trade_date >= 该日 (YYYY-MM-DD)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="重算所有行（不仅 pending）",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()
    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)
    report = run_eval(
        cfg,
        root=ROOT,
        since=args.since,
        force=bool(args.force),
        limit=args.limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
