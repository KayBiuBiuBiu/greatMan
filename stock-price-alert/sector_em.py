"""东方财富：个股 → 行业板块指数(BK) 解析、行业列表缓存、板块 K 线。"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import requests

from quote_eastmoney import normalize_bk_code, resolve_ut, secid_for
from utils import get_requests_verify

# 行业 clist 分页 / pz 修正后递增，用于使旧缓存自动失效并重拉全表
INDUSTRY_LIST_DISK_REV = 3

_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Origin": "https://quote.eastmoney.com",
    "Accept": "application/json,text/plain,*/*",
}

_ROUND_RESOLVE: dict[str, str | None] = {}
_INDUSTRY_N2BK: dict[str, str] = {}
_INDUSTRY_TS: float = 0.0
_sector_rlock = threading.RLock()


def clear_round_cache() -> None:
    """每轮监控开始前清空，避免同轮重复打接口。"""
    with _sector_rlock:
        _ROUND_RESOLVE.clear()


def _iter_clist_diff(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    diff = (data.get("data") or {}).get("diff") or {}
    if isinstance(diff, dict):
        keys = sorted(diff.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        for k in keys:
            yield diff[k]
    elif isinstance(diff, list):
        for x in diff:
            yield x


def _sector_em_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return dict(cfg.get("sector_em") or {})


def _em_get_json(url: str, params: dict[str, Any], *, timeout: float = 15.0) -> dict[str, Any] | None:
    """板块解析专用轻量请求（无 safe_get 长 sleep，避免批量超时）。"""
    from data_health import extra_backoff_sleep_sec, record_http_result

    es = extra_backoff_sleep_sec(url)
    if es > 0:
        time.sleep(es)
    try:
        r = requests.get(
            url,
            params=params,
            headers=_EM_HEADERS,
            timeout=timeout,
            verify=get_requests_verify(),
        )
        eff_url = str(getattr(r, "url", None) or url)
        if r.status_code != 200:
            record_http_result(eff_url, ok=False, status_code=r.status_code)
            return None
        try:
            out = r.json()
        except Exception:
            record_http_result(eff_url, ok=False, status_code=r.status_code)
            return None
        record_http_result(eff_url, ok=True, status_code=200)
        return out
    except Exception:
        record_http_result(url, ok=False, status_code=None)
        return None


def _cache_path(cfg: dict[str, Any], root: Path) -> Path:
    name = str(_sector_em_cfg(cfg).get("cache_filename") or "sector_index_cache.json")
    return root / name


def _load_cache_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "by_code": {}, "industry_name_to_bk": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "by_code": {}, "industry_name_to_bk": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "by_code": {}, "industry_name_to_bk": {}}
    raw.setdefault("by_code", {})
    raw.setdefault("industry_name_to_bk", {})
    if not isinstance(raw["by_code"], dict):
        raw["by_code"] = {}
    if not isinstance(raw["industry_name_to_bk"], dict):
        raw["industry_name_to_bk"] = {}
    return raw


def _save_cache_file(path: Path, data: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


_DEFAULT_PUSH2_HOSTS = (
    "https://push2.eastmoney.com",
    "http://82.push2.eastmoney.com",
    "http://77.push2.eastmoney.com",
)


def _api_hosts(cfg: dict[str, Any]) -> list[str]:
    """东财 push2 多域名回退（部分网络对单一 IP 会断连）。"""
    se = _sector_em_cfg(cfg)
    seen: set[str] = set()
    out: list[str] = []
    raw = se.get("api_hosts")
    if isinstance(raw, list):
        for h in raw:
            u = str(h or "").strip().rstrip("/")
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    single = str(se.get("api_host") or "").strip().rstrip("/")
    if single and single not in seen:
        seen.add(single)
        out.insert(0, single)
    for h in _DEFAULT_PUSH2_HOSTS:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out or list(_DEFAULT_PUSH2_HOSTS)


def _industry_fs_candidates(cfg: dict[str, Any]) -> list[str]:
    se = _sector_em_cfg(cfg)
    raw = se.get("industry_clist_fs")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return ["m:90+t:2", "m:90+t:3"]


def fetch_stock_industry_f127(code6: str, market: str, cfg: dict[str, Any]) -> str | None:
    """个股所属「行业」名称（东财 f127）。"""
    secid = secid_for(code6, market)
    ut = resolve_ut((cfg.get("sources") or {}).get("eastmoney_ut") or "ea")
    params = {
        "secid": secid,
        "fields": "f127",
        "fltt": "2",
        "invt": "2",
        "ut": ut,
    }
    for host in _api_hosts(cfg):
        url = f"{host}/api/qt/stock/get"
        j = _em_get_json(url, params, timeout=12.0)
        if not j:
            continue
        try:
            d = j.get("data") or {}
            v = d.get("f127")
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        except Exception:
            continue
    return None


def _fetch_industry_board_name_map(cfg: dict[str, Any]) -> dict[str, str]:
    """行业板块名称 → BK 代码（东财 clist）。"""
    ut = resolve_ut((cfg.get("sources") or {}).get("eastmoney_ut") or "ea")
    out: dict[str, str] = {}
    for fs in _industry_fs_candidates(cfg):
        pn = 1
        # 东财 clist 单页有效条数常 capped 在约 100；pz 过大时 total 又可能为 0，旧 while 会只拉一页
        pz = 100
        while True:
            params = {
                "pn": pn,
                "pz": pz,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": fs,
                "fields": "f12,f14",
                "ut": ut,
            }
            j = None
            for host in _api_hosts(cfg):
                url = f"{host}/api/qt/clist/get"
                j = _em_get_json(url, params, timeout=20.0)
                if j:
                    break
            if not j:
                break
            data = j.get("data") or {}
            total = int(data.get("total") or 0)
            batch = list(_iter_clist_diff(j))
            if not batch:
                break
            for row in batch:
                bk = str(row.get("f12") or "").strip().upper()
                name = str(row.get("f14") or "").strip()
                if bk.startswith("BK") and name:
                    out[name] = bk
            if total > 0:
                if pn * pz >= total:
                    break
            elif len(batch) < pz:
                break
            pn += 1
            if pn > 120:
                break
            time.sleep(0.2)
        if out:
            break
    return out


def _ensure_industry_map(cfg: dict[str, Any], cache_path: Path) -> dict[str, str]:
    global _INDUSTRY_N2BK, _INDUSTRY_TS
    se = _sector_em_cfg(cfg)
    ttl = float(se.get("industry_map_ttl_sec", 86400))
    now = time.time()
    with _sector_rlock:
        if _INDUSTRY_N2BK and (now - _INDUSTRY_TS) < ttl:
            return _INDUSTRY_N2BK

        disk = _load_cache_file(cache_path)
        n2bk_disk = disk.get("industry_name_to_bk") or {}
        rev_ok = int(disk.get("industry_list_disk_rev") or 0) == INDUSTRY_LIST_DISK_REV
        if isinstance(n2bk_disk, dict) and n2bk_disk and rev_ok:
            try:
                ts_s = str(disk.get("industry_map_updated_at") or "")
                if ts_s:
                    from datetime import datetime

                    t0 = datetime.fromisoformat(ts_s.replace("Z", "")).timestamp()
                    if now - t0 < ttl:
                        _INDUSTRY_N2BK = {
                            str(k).strip(): str(v).strip().upper()
                            for k, v in n2bk_disk.items()
                            if k and v
                        }
                        _INDUSTRY_TS = now
                        return _INDUSTRY_N2BK
            except Exception:
                pass

    n2bk = _fetch_industry_board_name_map(cfg)

    with _sector_rlock:
        if _INDUSTRY_N2BK and (time.time() - _INDUSTRY_TS) < ttl:
            return _INDUSTRY_N2BK
        disk = _load_cache_file(cache_path)
        n2bk_disk = disk.get("industry_name_to_bk") or {}
        if not n2bk:
            _INDUSTRY_N2BK = {
                str(k).strip(): str(v).strip().upper()
                for k, v in n2bk_disk.items()
                if k and v
            }
            _INDUSTRY_TS = time.time()
            return _INDUSTRY_N2BK

        _INDUSTRY_N2BK = n2bk
        _INDUSTRY_TS = time.time()
        disk["industry_name_to_bk"] = n2bk
        from datetime import datetime

        disk["industry_map_updated_at"] = datetime.now().isoformat(timespec="seconds")
        disk["industry_list_disk_rev"] = INDUSTRY_LIST_DISK_REV
        _save_cache_file(cache_path, disk)
        return _INDUSTRY_N2BK


def _match_industry_name_to_bk(name: str, n2bk: dict[str, str]) -> str | None:
    n = re.sub(r"\s+", "", str(name or "").strip())
    if not n:
        return None
    if n in n2bk:
        return n2bk[n]
    for k, bk in n2bk.items():
        kk = re.sub(r"\s+", "", k)
        if not kk:
            continue
        if kk == n or kk in n or n in kk:
            return bk
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
    解析个股对应东财行业板块 BK 代码：config 覆盖 > 文件缓存 > f127（失败则用 watchlist 行业名）+ 行业列表匹配。
    """
    s = str(code6).strip()
    c = s.zfill(6) if s.isdigit() and len(s) <= 6 else s
    with _sector_rlock:
        if c in _ROUND_RESOLVE:
            return _ROUND_RESOLVE[c]

        ov = cfg.get("sector_index_overrides") or {}
        if isinstance(ov, dict) and str(ov.get(c) or "").strip():
            bk0 = normalize_bk_code(str(ov[c]).strip())
            if bk0.startswith("BK"):
                _ROUND_RESOLVE[c] = bk0
                return bk0

        path = _cache_path(cfg, root)
        disk = _load_cache_file(path)
        by_code = disk.get("by_code") or {}
        if isinstance(by_code, dict) and str(by_code.get(c) or "").strip():
            bk0 = normalize_bk_code(str(by_code[c]).strip())
            if bk0.startswith("BK"):
                _ROUND_RESOLVE[c] = bk0
                return bk0

    f127 = fetch_stock_industry_f127(c, market, cfg)
    ind_name = (f127 or "").strip() or (str(fallback_industry or "").strip())
    if not ind_name:
        with _sector_rlock:
            _ROUND_RESOLVE[c] = None
        return None

    path = _cache_path(cfg, root)
    n2bk = _ensure_industry_map(cfg, path)
    bk = _match_industry_name_to_bk(ind_name, n2bk)
    if bk:
        bk = normalize_bk_code(bk)
        with _sector_rlock:
            disk = _load_cache_file(path)
            by_code = disk.get("by_code") or {}
            by_code = dict(by_code) if isinstance(by_code, dict) else {}
            by_code[c] = bk
            disk["by_code"] = by_code
            prev_im = disk.get("industry_name_to_bk")
            if not isinstance(prev_im, dict):
                prev_im = {}
            disk["industry_name_to_bk"] = {**prev_im, **n2bk}
            _save_cache_file(path, disk)
            _ROUND_RESOLVE[c] = bk
        return bk

    with _sector_rlock:
        _ROUND_RESOLVE[c] = bk
    return bk
