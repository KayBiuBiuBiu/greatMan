#!/usr/bin/env python3
"""全市场分层筛选 → 稳健核心池；持仓标签标的豁免清理、永久合并保留。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from position_tags import has_position_tag
from utils import safe_get

CLIST_URL = "http://77.push2.eastmoney.com/api/qt/clist/get"
# 沪深主板 + 创业板（不含科创板 fs）
FS_HS_CY = "m:1+t:2,m:0+t:6,m:0+t:80"
CLIST_FIELDS = (
    "f12,f14,f2,f3,f5,f6,f7,f20,f21,f22,f62,f100,f129,f134"
)


def _iter_clist_diff(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    diff = (data.get("data") or {}).get("diff") or {}
    if isinstance(diff, dict):
        keys = sorted(diff.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        for k in keys:
            yield diff[k]
    elif isinstance(diff, list):
        for x in diff:
            yield x


def _code_board_allowed(code: str) -> bool:
    c = code.strip()
    if len(c) != 6 or not c.isdigit():
        return False
    if c.startswith("688") or c.startswith("689"):
        return False
    # 北交所常见段（不含沪深创业板）
    if c.startswith("83") or c.startswith("87") or c.startswith("43") or c.startswith("92"):
        return False
    if c.startswith("60") or c.startswith("000") or c.startswith("001"):
        return True
    if c.startswith("002") or c.startswith("003"):
        return True
    if c.startswith("300"):
        return True
    if c.startswith("301"):
        return True  # 创业板注册制 301
    return False


def _name_risk_ok(name: str) -> bool:
    n = name.strip()
    if not n:
        return False
    up = n.upper()
    if "ST" in up or "*ST" in up or "PT" in up or "退" in n:
        return False
    return True


def _industry_blacklist_hit(industry: str, stock_name: str) -> bool:
    blob = f"{industry or ''}{stock_name or ''}"
    keys = (
        "房地产",
        "房地产开发",
        "水泥",
        "工程建设",
        "基础建设",
        "房屋建设",
        "装修建材",
        "建筑材料",
        "钢铁",
        "煤炭",
        "石油石化",
        "炼化及贸易",
        "银行",
        "保险",
        "证券",
        "多元金融",
        "化学原料",
        "化学制品",
        "农化制品",
        "塑料",
        "橡胶",
        "贵金属",
    )
    for k in keys:
        if k in blob:
            return True
    # 低端有色：铝/铅/锡（保留锂钴镍稀土新能源链条）
    if any(x in blob for x in ("铝", "铅", "锡")):
        if not any(x in blob for x in ("锂", "钴", "镍", "稀土", "能源金属", "储能", "新能源")):
            return True
    return False


def _industry_whitelist_hit(industry: str, stock_name: str) -> bool:
    blob = f"{industry or ''}{stock_name or ''}"
    keys = (
        "食品饮料",
        "白酒",
        "啤酒",
        "调味发酵",
        "食品加工",
        "家电",
        "家居",
        "纺织",
        "服装",
        "商贸零售",
        "社会服务",
        "机械设备",
        "通用设备",
        "专用设备",
        "自动化",
        "军工",
        "国防",
        "汽车零部件",
        "汽车零",
        "电池",
        "光伏设备",
        "风电",
        "电网设备",
        "电机",
        "能源金属",
        "小金属",
        "稀有金属",
        "稀土",
        "消费电子",
        "半导体",
        "通信",
        "光学光电子",
        "元件",
        "电子化学品",
        "电力设备",
        "环保",
        "轻工制造",
        "美容护理",
        "医药生物",
        "医疗器械",
        "医疗服务",
        "中药",
        "化学制药",
        "生物制品",
    )
    return any(k in blob for k in keys)


def _industry_allowed(industry: str, stock_name: str) -> bool:
    if _industry_blacklist_hit(industry, stock_name):
        return False
    if _industry_whitelist_hit(industry, stock_name):
        return True
    # 中性拓展：未命中白名单则拒绝入「稳健池」（减少周期/主题噪声）
    blob = industry or ""
    neutral = (
        "电子",
        "计算机",
        "通信",
        "环保",
        "公用事业",
        "汽车",
        "传媒",
        "机械设备",
        "电力设备",
    )
    return any(k in blob for k in neutral)


def fetch_all_hs_cy_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pn = 1
    pz = 500
    while True:
        params = {
            "pn": pn,
            "pz": pz,
            "fs": FS_HS_CY,
            "fields": CLIST_FIELDS,
        }
        r = safe_get(CLIST_URL, params=params, timeout=30)
        if r is None:
            raise RuntimeError("safe_get 请求失败")
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or {}
        total = int(data.get("total") or 0)
        batch = list(_iter_clist_diff(j))
        if not batch:
            break
        rows.extend(batch)
        if pn * pz >= total:
            break
        pn += 1
        time.sleep(0.25)
    return rows


def _float_mv_yuan(row: dict[str, Any]) -> float:
    v = row.get("f21") or row.get("f20") or 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _amount_yuan(row: dict[str, Any]) -> float:
    try:
        return float(row.get("f6") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _price_yuan(row: dict[str, Any]) -> float | None:
    raw = row.get("f2")
    if raw is None or raw == 0:
        return None
    try:
        return float(raw) / 100.0
    except (TypeError, ValueError):
        return None


def layered_filter(
    rows: list[dict[str, Any]],
    *,
    sr: dict[str, Any],
) -> list[dict[str, Any]]:
    min_p = float(sr.get("min_price", 5.0))
    max_p = float(sr.get("max_price", 32.0))
    min_mv = float(sr.get("min_float_mv_yi", 28.0)) * 1e8
    max_mv = float(sr.get("max_float_mv_yi", 750.0)) * 1e8
    min_amt = float(sr.get("min_daily_amount_wan", 6500.0)) * 10000.0

    out: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("f12") or "").strip()
        name = str(row.get("f14") or "").strip()
        ind = str(row.get("f100") or "").strip()

        if not _code_board_allowed(code):
            continue
        if not _name_risk_ok(name):
            continue

        price = _price_yuan(row)
        if price is None or price < min_p or price > max_p:
            continue

        fmv = _float_mv_yuan(row)
        if fmv < min_mv or fmv > max_mv:
            continue

        amt = _amount_yuan(row)
        if amt < min_amt:
            continue

        # 停牌 / 长时间无成交
        if float(row.get("f5") or 0.0) <= 0 and amt <= 0:
            continue

        if not _industry_allowed(ind, name):
            continue

        mkt = "sh" if code.startswith("6") else "sz"
        out.append({"name": name, "code": code, "market": mkt, "industry": ind})
    return out


def _watch_template(default_note: str = "选股池写入") -> dict[str, Any]:
    return {
        "enabled": True,
        "cost_price": 0.0,
        "hold_shares": 0,
        "alert_mode": "breach",
        "alert_below": None,
        "alert_above": None,
        "note": default_note,
        "tags": "",
        "industry": "",
    }


def merge_tagged_holdings(
    prev_watch: list[dict[str, Any]],
    scanned: list[dict[str, Any]],
    *,
    note: str,
) -> list[dict[str, Any]]:
    """
    带持仓标签：永久保留，不被本轮扫描结果剔除。
    无标签：以本轮扫描池为准重建（旧池中未入选者删除）。
    """
    by_code: dict[str, dict[str, Any]] = {}
    for w in prev_watch:
        if not isinstance(w, dict):
            continue
        c = str(w.get("code") or "").strip()
        if c and has_position_tag(w):
            by_code[c] = dict(w)

    for s in scanned:
        c = str(s.get("code") or "").strip()
        if not c:
            continue
        if c in by_code and has_position_tag(by_code[c]):
            continue
        ent = _watch_template(note)
        ent.update(
            {
                "name": str(s.get("name") or c),
                "code": c,
                "market": str(s.get("market") or "sh"),
                "industry": str(s.get("industry") or ""),
            }
        )
        by_code[c] = ent

    return list(by_code.values())


def _parse_iso_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = str(s).strip()
        if "T" in s and s.endswith("Z"):
            s = s[:-1]
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def scan_and_save(cfg_path: Path, *, force: bool = False) -> int:
    sys.path.insert(0, str(Path(__file__).parent))

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    sr = dict(raw.get("scan_rule") or {})
    meta = dict(raw.get("scan_meta") or {})
    scan_days = float(sr.get("full_scan_interval_days", 3.0))

    last_s = meta.get("last_full_scan_iso") or meta.get("last_full_scan_ts")
    last_dt = _parse_iso_ts(str(last_s)) if last_s else None
    now = datetime.now()
    if last_dt is not None and last_dt.tzinfo is not None:
        last_dt = last_dt.replace(tzinfo=None)
    if (
        not force
        and last_dt is not None
        and (now - last_dt) < timedelta(days=scan_days)
    ):
        left = scan_days - (now - last_dt).total_seconds() / 86400.0
        print(
            f"[扫描跳过] 距离上次全量重筛不足 {scan_days:g} 天（约还剩 {max(0.0, left):.1f} 天）。"
            f" 强制请使用：python run_alert.py --scan --force-scan"
        )
        return 0

    target_n = int(raw.get("scan_pool_max", 450))
    target_n = max(200, min(800, target_n))

    print("[接口抓取] 正在拉取沪深主板+创业板列表（不含科创板/北交所）…")
    rows = fetch_all_hs_cy_rows()
    print(f"[接口完成] 原始行数 {len(rows)}，开始分层筛选…")

    picked = layered_filter(rows, sr=sr)
    print(f"[筛选完成] 规则命中 {len(picked)} 只，目标写入约 {target_n} 只（截断取整）")

    picked = picked[:target_n]
    prev_watch = raw.get("watchlist") or []
    if not isinstance(prev_watch, list):
        prev_watch = []

    note = str(sr.get("watchlist_note", "选股池写入"))
    merged = merge_tagged_holdings(prev_watch, picked, note=note)

    raw["watchlist"] = merged
    meta["last_full_scan_iso"] = datetime.now().isoformat(timespec="seconds")
    meta["last_scan_pool_count"] = len(picked)
    raw["scan_meta"] = meta

    cfg_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tagged_n = sum(1 for w in merged if isinstance(w, dict) and has_position_tag(w))
    print(
        f"[成功] 已写入 watchlist 共 {len(merged)} 条（其中持仓标签保留 {tagged_n} 条，扫描入池 {len(picked)} 条）"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", type=Path, default=Path(__file__).parent / "config.json")
    ap.add_argument(
        "--force",
        "--force-scan",
        action="store_true",
        dest="force_scan",
        help="忽略扫描间隔，立即全量重筛",
    )
    args = ap.parse_args()
    return scan_and_save(args.config, force=args.force_scan)


if __name__ == "__main__":
    raise SystemExit(main())
