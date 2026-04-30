#!/usr/bin/env python3
"""
生成 / 更新「本地主表」a_share_names.json（代码→简称）。
run_alert.get_stock_name 优先读此文件，命中则不走网络，监控会快很多。

拉取方式：东财 clist 分页（与 stock_scanner 同源，仅需 requests），
失败时再尝试 akshare.stock_zh_a_spot_em。

用法（建议定期在本机执行一次，新股多时可更勤）：
  python build_a_share_name_table.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "a_share_names.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils import get_requests_verify

# 东财 A 股聚合；URL 与 stock_scanner 一致（部分环境 https 易失败）
CLIST_URLS = (
    "http://77.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
FS_ALL_A = "m:0+t:6,m:0+t:80,m:0+t:81,s:2048,m:1+t:2,m:1+t:23,m:0+t:82"
CLIST_FIELDS = "f12,f14"


def _iter_clist_diff(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    diff = (data.get("data") or {}).get("diff") or {}
    if isinstance(diff, dict):
        keys = sorted(diff.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        for k in keys:
            yield diff[k]
    elif isinstance(diff, list):
        for x in diff:
            yield x


def _clist_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """先走 safe_get；失败则用短等待直连（本脚本一次性任务）。"""
    from utils import safe_get

    r = safe_get(url, params=params, timeout=45)
    if r is not None and r.status_code == 200:
        return r.json()
    import random

    import requests

    time.sleep(random.uniform(0.2, 0.6))
    r2 = requests.get(
        url,
        params=params,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=45,
        verify=get_requests_verify(),
    )
    r2.raise_for_status()
    return r2.json()


def fetch_via_eastmoney_clist() -> dict[str, str]:
    mapping: dict[str, str] = {}
    last_err: Exception | None = None
    for base_url in CLIST_URLS:
        try:
            pn = 1
            pz = 500
            while True:
                params = {
                    "pn": pn,
                    "pz": pz,
                    "fs": FS_ALL_A,
                    "fields": CLIST_FIELDS,
                }
                j = _clist_get_json(base_url, params)
                data = j.get("data") or {}
                total = int(data.get("total") or 0)
                batch = list(_iter_clist_diff(j))
                if not batch:
                    break
                for row in batch:
                    code = str(row.get("f12") or "").strip().zfill(6)
                    name = str(row.get("f14") or "").strip()
                    if len(code) == 6 and code.isdigit() and name:
                        mapping[code] = name
                if pn * pz >= total:
                    break
                pn += 1
                time.sleep(0.15)
            if mapping:
                return mapping
        except Exception as e:
            last_err = e
            mapping.clear()
            continue
    if last_err:
        raise RuntimeError(str(last_err)) from last_err
    raise RuntimeError("东财 clist 无数据")


def fetch_via_akshare() -> dict[str, str]:
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    codes = df["代码"].astype(str).str.strip().str.zfill(6)
    names = df["名称"].astype(str).str.strip()
    return dict(zip(codes, names))


def main() -> int:
    mapping: dict[str, str] = {}
    try:
        print("正在拉取东财全市场列表（分页 clist）…")
        mapping = fetch_via_eastmoney_clist()
    except Exception as e:
        print(f"东财 clist 失败：{e}", file=sys.stderr)
        try:
            print("改用 akshare.stock_zh_a_spot_em …")
            mapping = fetch_via_akshare()
        except ImportError:
            print("未安装 akshare，且东财接口失败。请检查网络后重试。", file=sys.stderr)
            return 1
        except Exception as e2:
            print(f"akshare 也失败：{e2}", file=sys.stderr)
            return 1

    meta = {
        "_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_count": len(mapping),
        "_source": "eastmoney_clist",
    }
    payload = {**meta, **mapping}
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {len(mapping)} 条 -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
