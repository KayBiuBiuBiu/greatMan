"""申万行业：本地 stock_to_sw + sector_index_cache；无东方财富网络请求。"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from quote_tushare import resolved_stock_to_sw_path

_sector_rlock = threading.RLock()
_ROUND_RESOLVE: dict[str, str | None] = {}
_STOCK_SW_MTIME: float = 0.0
_STOCK_SW_MAP: dict[str, str] = {}
_SW_L1_NAMES_MTIME: float = 0.0
_SW_L1_NAMES: dict[str, str] = {}


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
    优先级：sector_index_overrides > sector_index_cache.by_code > stock_to_sw.json
    > Tushare index_member_all（单票）。
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

    ts3 = _resolve_sw_via_tushare(c, market, cfg)
    if ts3:
        with _sector_rlock:
            _ROUND_RESOLVE[c] = ts3
        persist_resolved_sw(c, ts3, cfg, root)
        return ts3

    with _sector_rlock:
        _ROUND_RESOLVE[c] = None
    return None


def _code_to_ts_code(code6: str, market: str) -> str:
    c = str(code6).strip().zfill(6)
    m = str(market or "").strip().lower()
    if m in ("sh", "sse") or c.startswith("6"):
        return f"{c}.SH"
    if m in ("bj", "bse") or c.startswith(("4", "8")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _resolve_sw_via_tushare(code6: str, market: str, cfg: dict[str, Any]) -> str | None:
    """本地映射缺失时，按 ts_code 查 Tushare index_member_all（单票）。"""
    c = str(code6).strip().zfill(6)
    if len(c) != 6 or not c.isdigit():
        return None
    try:
        from quote_tushare import _get_pro, configure_tushare_from_sources

        src = cfg.get("sources") if isinstance(cfg.get("sources"), dict) else {}
        ts_cfg = src.get("tushare") if isinstance(src.get("tushare"), dict) else {}
        if not bool(ts_cfg.get("enabled", False)):
            return None
        configure_tushare_from_sources(src)
        pro = _get_pro()
        if pro is None:
            return None
        ts_code = _code_to_ts_code(c, market)
        df = pro.index_member_all(is_new="Y", ts_code=ts_code)
        if df is None or getattr(df, "empty", True):
            return None
        row = df.iloc[0]
        for col in ("l1_code", "L1_code"):
            raw = str(row.get(col) or "").strip()
            ts = _normalize_sw_ts(raw)
            if ts:
                return ts
    except Exception:
        logging.getLogger(__name__).debug("tushare sw_l1 lookup", exc_info=True)
    return None


def _sw_l1_names_path(root: Path) -> Path:
    return root / "data" / "sw_l1_names.json"


def load_sw_l1_names(root: Path) -> dict[str, str]:
    """801xxx.SI → 申万一级中文名。"""
    global _SW_L1_NAMES_MTIME, _SW_L1_NAMES
    path = _sw_l1_names_path(root)
    try:
        mt = path.stat().st_mtime
    except OSError:
        mt = 0.0
    with _sector_rlock:
        if _SW_L1_NAMES and mt == _SW_L1_NAMES_MTIME:
            return dict(_SW_L1_NAMES)
    out: dict[str, str] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if str(k).startswith("_"):
                    continue
                ts = _normalize_sw_ts(str(k))
                nm = str(v or "").strip()
                if ts and nm:
                    out[ts] = nm
    with _sector_rlock:
        _SW_L1_NAMES = out
        _SW_L1_NAMES_MTIME = mt
    return dict(out)


def sw_l1_display_name(sw_ts: str | None, *, root: Path) -> str:
    ts = _normalize_sw_ts(str(sw_ts or "").strip()) if sw_ts else None
    if not ts:
        return ""
    names = load_sw_l1_names(root)
    return names.get(ts) or ts


def resolve_stock_sw_l1_ts(
    code6: str,
    cfg: dict[str, Any],
    *,
    root: Path,
    pack: dict[str, Any] | None = None,
    market: str | None = None,
    sw_hint: str | None = None,
) -> str | None:
    """个股申万一级 ts_code：pack.sector_bk → sw_hint → resolve_sector_bk。"""
    if isinstance(pack, dict):
        bk = _normalize_sw_ts(str(pack.get("sector_bk") or "").strip())
        if bk:
            return bk
    hint = _normalize_sw_ts(str(sw_hint or "").strip())
    if hint:
        return hint
    c = str(code6).strip().zfill(6)
    if len(c) != 6 or not c.isdigit():
        return None
    mkt = str(market or "").strip().lower()
    if not mkt and isinstance(pack, dict):
        rule = pack.get("rule") if isinstance(pack.get("rule"), dict) else {}
        mkt = str(rule.get("market") or "").strip().lower()
    return resolve_sector_bk(c, mkt or "sh", cfg, root=root)


def format_sector_console_line(
    code6: str,
    cfg: dict[str, Any],
    *,
    root: Path,
    pack: dict[str, Any] | None = None,
    market: str | None = None,
    sw_hint: str | None = None,
) -> str:
    """控制台板块行：所有标的统一展示。"""
    sw = resolve_stock_sw_l1_ts(
        code6, cfg, root=root, pack=pack, market=market, sw_hint=sw_hint
    )
    if not sw:
        return "      └ 板块：—（未解析到申万一级）"
    name = sw_l1_display_name(sw, root=root)
    if name and name != sw:
        return f"      └ 板块：{name}（申万一级）"
    return f"      └ 板块：{sw}"


def format_global_context_line(code6: str) -> str:
    """
    控制台全球背景行：美股 + 伦铜。

    返回格式：
      └ 🌍 美股对标↑+2.3% | 📦 伦铜↓-1.0% | 💚 很强势，加仓
    若无数据则返回空字符串。
    """
    try:
        from global_context_display import get_stock_global_context

        ctx = get_stock_global_context(code6)
        if ctx and ctx.get("display_line"):
            return f"      └ {ctx['display_line']}"
    except Exception:
        logging.getLogger(__name__).debug(
            "全球背景显示异常 %s", code6, exc_info=True
        )
    return ""


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
