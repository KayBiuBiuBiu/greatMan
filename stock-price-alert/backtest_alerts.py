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


def hit_thresholds_from_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """从 merged cfg 构造 evaluate_row / 网格搜索用的阈值表。"""
    al = cfg.get("alert_log") or {}
    pse = al.get("position_suggestion_eval")
    if not isinstance(pse, dict):
        pse = {}
    she = al.get("strategy_hit_eval")
    if not isinstance(she, dict):
        she = {}
    rst = al.get("risk_stop_take_eval")
    if not isinstance(rst, dict):
        rst = {}
    return {
        "bearish_hit_threshold_pct_1d": float(
            al.get("bearish_hit_threshold_pct_1d", -2.0)
        ),
        "bearish_hit_threshold_pct_3d": float(
            al.get("bearish_hit_threshold_pct_3d", -2.5)
        ),
        "bearish_hit_threshold_pct_5d": float(
            al.get("bearish_hit_threshold_pct_5d", -3.0)
        ),
        "position_suggestion_eval": pse,
        "strategy_hit_eval": she,
        "risk_stop_take_eval": rst,
    }


def evaluate_hit_report_only(
    cfg: dict[str, Any],
    *,
    root: Path,
    since: str | None = None,
) -> dict[str, Any]:
    """
    不重写 alert_events：按当前 cfg 阈值对事件重算 hit/收益并汇总。
    供 auto_tune 网格搜索；数据库需已有足够 K 线以计算远期收益。
    """
    from alert_log_store import resolve_alert_db_path

    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None or not db_path.is_file():
        return {"by_alert_type": {}, "rows_evaluated": 0, "db_path": str(db_path or "")}
    thresholds = hit_thresholds_from_cfg(cfg)
    rows: list[Any] = []
    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        q = "SELECT * FROM alert_events WHERE 1=1"
        params: list[Any] = []
        if since:
            q += " AND anchor_trade_date >= ?"
            params.append(since[:10])
        q += " ORDER BY id ASC"
        rows = list(conn.execute(q, params).fetchall())
        agg: dict[str, dict[str, Any]] = {}
        for row in rows:
            r1, r3, r5, hit = evaluate_row(conn, row, thresholds)
            t = str(row["alert_type"])
            b = agg.setdefault(
                t,
                {
                    "_n": 0,
                    "_scored": 0,
                    "_hits": 0,
                    "_s1": 0.0,
                    "_c1": 0,
                    "_s3": 0.0,
                    "_c3": 0,
                    "_s5": 0.0,
                    "_c5": 0,
                },
            )
            b["_n"] += 1
            for val, key_s, key_c in (
                (r1, "_s1", "_c1"),
                (r3, "_s3", "_c3"),
                (r5, "_s5", "_c5"),
            ):
                if val is not None:
                    b[key_s] += float(val)
                    b[key_c] += 1
            if hit is not None:
                b["_scored"] += 1
                if int(hit) == 1:
                    b["_hits"] += 1
    finally:
        conn.close()

    by_type: dict[str, dict[str, Any]] = {}
    for t, b in agg.items():
        n = int(b["_n"])
        ns = int(b["_scored"])
        nh = int(b["_hits"])
        by_type[t] = {
            "n": n,
            "n_hit_scored": ns,
            "hit_rate": (nh / ns) if ns else None,
            "avg_ret_1d": (b["_s1"] / b["_c1"]) if b["_c1"] else None,
            "avg_ret_3d": (b["_s3"] / b["_c3"]) if b["_c3"] else None,
            "avg_ret_5d": (b["_s5"] / b["_c5"]) if b["_c5"] else None,
        }
    return {
        "by_alert_type": by_type,
        "rows_evaluated": len(rows),
        "db_path": str(db_path),
    }


def run_eval(
    cfg: dict[str, Any],
    *,
    root: Path,
    since: str | None,
    force: bool,
    reeval_missing_returns: bool,
    limit: int | None,
) -> dict[str, Any]:
    from alert_log_store import resolve_alert_db_path

    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None:
        raise SystemExit("请在配置中启用 alert_log.enabled。")
    thresholds = hit_thresholds_from_cfg(cfg)
    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        q = "SELECT * FROM alert_events WHERE 1=1"
        params: list[Any] = []
        if force:
            pass
        elif reeval_missing_returns:
            if since:
                q += """ AND (
                    (eval_status = 'pending' AND anchor_trade_date >= ?)
                    OR (eval_status = 'done' AND ret_5d IS NULL)
                )"""
                params.append(since[:10])
            else:
                q += " AND (eval_status = 'pending' OR (eval_status = 'done' AND ret_5d IS NULL))"
        else:
            q += " AND eval_status = 'pending'"
            if since:
                q += " AND anchor_trade_date >= ?"
                params.append(since[:10])
        if since and force:
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
    ap.add_argument(
        "--reeval-missing-returns",
        action="store_true",
        help="重算 pending 以及已 done 但 ret_5d 仍为空的记录（适合补全历史 K 线后回填）",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()
    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)
    if bool(args.force) and bool(args.reeval_missing_returns):
        print(
            "已指定 --force，将重算全部行（忽略 --reeval-missing-returns 的筛选）",
            file=sys.stderr,
        )
    report = run_eval(
        cfg,
        root=ROOT,
        since=args.since,
        force=bool(args.force),
        reeval_missing_returns=bool(args.reeval_missing_returns),
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
