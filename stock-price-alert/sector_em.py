"""申万行业：本地 stock_to_sw + sector_index_cache；无东方财富网络请求。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from quote_tushare import resolved_stock_to_sw_path

_sector_rlock = threading.RLock()
_ROUND_RESOLVE: dict[str, str | None] = {}
_STOCK_SW_MTIME: float = 0.0
_STOCK_SW_MAP: dict[str, str] = {}


def clear_round_cache() -> None:
    with _sector_rlock:
        _ROUND_RESOLVE.clear()


def _sector_em_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return dict(cfg.get("sector_em") or {})


def _cache_path(cfg: dict[str, Any], root: Path) -> Path:
    name = str(_sector_em_cfg(cfg).get("cache_filename") or "sector_index_cache.json")
    return root / name


def sector_index_cache_path(cfg: dict[str, Any], root: Path) -> Path:
    return _cache_path(cfg, root)


def _load_cache_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 2, "by_code": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "by_code": {}}
    if not isinstance(raw, dict):
        return {"version": 2, "by_code": {}}
    raw.setdefault("by_code", {})
    if not isinstance(raw["by_code"], dict):
        raw["by_code"] = {}
    return raw


def _save_cache_file(path: Path, data: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _normalize_sw_ts(raw: str) -> str | None:
    s = str(raw).strip().upper()
    if len(s) >= 9 and s.endswith(".SI") and s[:-3].isdigit():
        return s
    return None


def _load_sw_flat(path: Path) -> dict[str, str]:
    from sw_member_cache import load_stock_to_sw_map

    return load_stock_to_sw_map(path)


def _sw_map_cached(root: Path) -> dict[str, str]:
    global _STOCK_SW_MTIME, _STOCK_SW_MAP
    path = resolved_stock_to_sw_path(root)
    try:
        mt = path.stat().st_mtime
    except OSError:
        mt = 0.0
    with _sector_rlock:
        if _STOCK_SW_MAP and mt == _STOCK_SW_MTIME:
            return dict(_STOCK_SW_MAP)
    m = _load_sw_flat(path)
    with _sector_rlock:
        _STOCK_SW_MAP = m
        _STOCK_SW_MTIME = mt
    return dict(m)


def fetch_stock_industry_f127(
    _code6: str,
    _market: str,
    _cfg: dict[str, Any],
) -> str | None:
    """已移除东财 f127；请使用 stock_to_sw 与 Tushare 行业字段。"""
    return None


def resolve_sector_bk(
    code6: str,
    market: str,
    cfg: dict[str, Any],
    *,
    root: Path,
    fallback_industry: str | None = None,
) -> str | None:
    """
    解析个股对应申万行业指数 ts_code（如 801780.SI）。
    优先级：sector_index_overrides > sector_index_cache.by_code > stock_to_sw.json。
    （函数名保留以兼容调用方；不再返回东财 BK。）
    """
    _ = market
    _ = fallback_industry
    s = str(code6).strip()
    c = s.zfill(6) if s.isdigit() and len(s) <= 6 else s
    if len(c) != 6 or not c.isdigit():
        return None
    with _sector_rlock:
        if c in _ROUND_RESOLVE:
            return _ROUND_RESOLVE[c]

    ov = cfg.get("sector_index_overrides") or {}
    if isinstance(ov, dict):
        raw_ov = str(ov.get(c) or "").strip()
        ts0 = _normalize_sw_ts(raw_ov)
        if ts0:
            with _sector_rlock:
                _ROUND_RESOLVE[c] = ts0
            return ts0

    path = _cache_path(cfg, root)
    disk = _load_cache_file(path)
    by_code = disk.get("by_code") or {}
    if isinstance(by_code, dict):
        raw_b = str(by_code.get(c) or "").strip()
        ts1 = _normalize_sw_ts(raw_b)
        if ts1:
            with _sector_rlock:
                _ROUND_RESOLVE[c] = ts1
            return ts1

    mp = _sw_map_cached(root)
    ts2 = mp.get(c)
    if ts2:
        with _sector_rlock:
            _ROUND_RESOLVE[c] = ts2
        return ts2

    with _sector_rlock:
        _ROUND_RESOLVE[c] = None
    return None


def persist_resolved_sw(code6: str, sw_ts: str, cfg: dict[str, Any], root: Path) -> None:
    """将解析到的申万代码写入 sector_index_cache 便于离线复用。"""
    c = str(code6).strip().zfill(6)
    ts = _normalize_sw_ts(sw_ts)
    if not ts:
        return
    path = _cache_path(cfg, root)
    disk = _load_cache_file(path)
    bc = dict(disk.get("by_code") or {})
    bc[c] = ts
    disk["by_code"] = bc
    disk["version"] = 2
    _save_cache_file(path, disk)
