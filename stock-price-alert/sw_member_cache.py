"""申万行业：股票代码 → 申万一级指数 ts_code（801xxx.SI），本地 JSON 缓存。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REL_PATH = "data/stock_to_sw.json"
_META = "_meta"


def default_stock_to_sw_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parent
    return base / DEFAULT_REL_PATH


def load_stock_to_sw_map(path: Path) -> dict[str, str]:
    """返回 6 位数字代码 → 801xxx.SI。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("by_code") if isinstance(raw.get("by_code"), dict) else raw
    out: dict[str, str] = {}
    for k, v in inner.items():
        if str(k).startswith("_"):
            continue
        ck = str(k).strip().zfill(6)
        if len(ck) != 6 or not ck.isdigit():
            continue
        ts = str(v).strip().upper()
        if len(ts) >= 9 and ts.endswith(".SI") and ts[:-3].isdigit():
            out[ck] = ts
    return out


def refresh_stock_to_sw_cache(path: Path, *, pro: Any, sleep_sec: float = 0.12) -> int:
    """
    拉取申万一级成分映射并写入 path。
    优先 index_member_all（含 l1_code）；失败则 sw_index_classify(L1)+sw_index_member。
    """
    by_code: dict[str, str] = {}

    def add_pair(stock_ts: str, sw_ts: str) -> None:
        st = str(stock_ts or "").strip().upper()
        sw = str(sw_ts or "").strip().upper()
        if "." not in st:
            return
        sym = st.split(".", 1)[0].strip().zfill(6)
        if len(sym) != 6 or not sym.isdigit():
            return
        if len(sw) >= 9 and sw.endswith(".SI") and sw[:-3].isdigit():
            by_code[sym] = sw

    # 1) index_member_all
    try:
        df = pro.index_member_all(is_new="Y")
        if df is not None and not getattr(df, "empty", True):
            for col_stock, col_l1 in (
                ("con_code", "l1_code"),
                ("ts_code", "l1_code"),
                ("con_code", "L1_code"),
            ):
                if col_stock in df.columns and col_l1 in df.columns:
                    for _, row in df.iterrows():
                        add_pair(str(row.get(col_stock) or ""), str(row.get(col_l1) or ""))
                    break
    except Exception:
        pass

    # 2) 分类 + sw_index_member
    if len(by_code) < 100:
        classify = None
        for kwargs in (
            {"level": "L1", "src": "SW2021"},
            {"level": "L1", "src": "SW"},
            {"level": "L1"},
        ):
            try:
                classify = pro.index_classify(**kwargs)
                if classify is not None and not getattr(classify, "empty", True):
                    break
            except Exception:
                classify = None
        if classify is not None and not getattr(classify, "empty", True):
            code_col = "index_code" if "index_code" in classify.columns else None
            if code_col:
                for _, crow in classify.iterrows():
                    ic = str(crow.get(code_col) or "").strip().upper()
                    if not ic.endswith(".SI"):
                        continue
                    try:
                        mdf = pro.sw_index_member(index_code=ic)
                    except Exception:
                        continue
                    if mdf is None or getattr(mdf, "empty", True):
                        continue
                    scol = "con_code" if "con_code" in mdf.columns else None
                    if not scol:
                        continue
                    for _, mrow in mdf.iterrows():
                        add_pair(str(mrow.get(scol) or ""), ic)
                    time.sleep(max(0.0, float(sleep_sec)))

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        _META: {
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(by_code),
            "source": "tushare_sw",
        },
        "by_code": by_code,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(by_code)
