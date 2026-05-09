"""板块/主题多维度轻量交叉：相对大盘强弱、板块均线位、个股相对板块。

三维度互补：
- sector_rs_vs_index：板块近 5 日收益相对上证（或 pack 内 index_5d_ret）
- sector_above_ma20：板块收盘是否在 MA20 上方（弱势板块过滤）
- stock_vs_sector_rs：个股 5 日收益相对板块（避免板块内掉队）

支持 vote（票数）与 weighted（加权得分）两种汇总方式；有效维度不足时默认不拦截。
"""

from __future__ import annotations

from typing import Any, Literal

DimKey = Literal["sector_rs_vs_index", "sector_above_ma20", "stock_vs_sector_rs"]

DIM_ORDER: tuple[DimKey, ...] = (
    "sector_rs_vs_index",
    "sector_above_ma20",
    "stock_vs_sector_rs",
)

DIM_LABEL_CN: dict[str, str] = {
    "sector_rs_vs_index": "板块5日相对大盘",
    "sector_above_ma20": "板块站上MA20",
    "stock_vs_sector_rs": "个股相对板块5日",
}


def _five_day_return(closes: list[float] | tuple[float, ...]) -> float | None:
    if not closes or len(closes) < 6:
        return None
    try:
        a = float(closes[-6])
        b = float(closes[-1])
    except (TypeError, ValueError):
        return None
    if a <= 0 or b <= 0:
        return None
    return b / a - 1.0


def _dim_sector_rs_vs_index(
    pack: dict[str, Any],
    margin: float,
) -> bool | None:
    """板块 5 日收益不低于大盘 5 日 + margin（margin 可为负，允许略弱于大盘）。"""
    idx = pack.get("index_5d_ret")
    sc = list(pack.get("sector_closes") or [])
    sec5 = _five_day_return(sc)
    if sec5 is None or idx is None:
        return None
    try:
        idx_f = float(idx)
    except (TypeError, ValueError):
        return None
    return bool(sec5 >= idx_f + float(margin))


def _dim_sector_above_ma20(
    pack: dict[str, Any],
    ma_tol: float,
) -> bool | None:
    sk = pack.get("sector_kline")
    sc = list(pack.get("sector_closes") or [])
    if not isinstance(sk, dict) or not sc:
        return None
    try:
        ma20 = float(sk.get("ma20") or 0.0)
        last = float(sc[-1])
    except (TypeError, ValueError):
        return None
    if ma20 <= 0 or last <= 0:
        return None
    tol = max(0.0, float(ma_tol))
    return bool(last >= ma20 * (1.0 - tol))


def _dim_stock_vs_sector_rs(
    pack: dict[str, Any],
    max_lag: float,
) -> bool | None:
    """个股 5 日相对板块：个股收益不低于板块 5 日 - max_lag。"""
    st = list(pack.get("closes") or [])
    sc = list(pack.get("sector_closes") or [])
    s5 = _five_day_return(st)
    b5 = _five_day_return(sc)
    if s5 is None or b5 is None:
        return None
    lag = max(0.0, float(max_lag))
    return bool(s5 >= b5 - lag)


def evaluate_sector_buy_cross_dims(
    pack: dict[str, Any],
    scc: dict[str, Any],
) -> dict[str, Any]:
    """
    计算各维度结果。返回 dict：
    dims: { key: True|False|None }, evaluated_count, pass_count, labels for failures.
    """
    margin = float(scc.get("sector_rs_vs_index_margin", -0.003) or 0.0)
    ma_tol = float(scc.get("ma20_tolerance", 0.002) or 0.0)
    max_lag = float(scc.get("stock_vs_sector_max_lag", 0.02) or 0.0)

    dims: dict[str, bool | None] = {
        "sector_rs_vs_index": _dim_sector_rs_vs_index(pack, margin),
        "sector_above_ma20": _dim_sector_above_ma20(pack, ma_tol),
        "stock_vs_sector_rs": _dim_stock_vs_sector_rs(pack, max_lag),
    }
    evaluated = {k: v for k, v in dims.items() if v is not None}
    pass_count = sum(1 for v in evaluated.values() if v)
    failed = [DIM_LABEL_CN[k] for k, v in evaluated.items() if v is False]
    return {
        "dims": dims,
        "evaluated_count": len(evaluated),
        "pass_count": pass_count,
        "failed_labels": failed,
    }


def sector_buy_cross_block_reason(
    pack: dict[str, Any],
    scc: dict[str, Any] | None,
) -> str | None:
    """
    若应拦截买入则返回原因文案，否则 None。
    依赖 pack：sector_bk, sector_closes, sector_kline, closes, index_5d_ret。
    """
    if not scc or not bool(scc.get("enabled", False)):
        return None
    if bool(scc.get("require_sector_bk", True)) and not (
        str(pack.get("sector_bk") or "").strip()
    ):
        return None

    ev = evaluate_sector_buy_cross_dims(pack, scc)
    n_ev = int(ev["evaluated_count"])
    min_ev = int(scc.get("min_evaluated_dims", 2) or 2)
    if n_ev < max(1, min_ev):
        return None

    mode = str(scc.get("mode", "vote") or "vote").strip().lower()
    if mode == "weighted":
        weights_in = scc.get("weights")
        weights: dict[str, float] = {}
        if isinstance(weights_in, dict):
            for k, v in weights_in.items():
                try:
                    weights[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass
        thr = float(scc.get("pass_weighted_threshold", 0.5) or 0.5)
        wsum = 0.0
        acc = 0.0
        dims_map: dict[str, bool | None] = ev["dims"]
        for key in DIM_ORDER:
            ok = dims_map.get(key)
            if ok is None:
                continue
            w = float(weights.get(key, 1.0))
            if w <= 0:
                continue
            wsum += w
            acc += w if ok else 0.0
        if wsum <= 1e-12:
            return None
        score = acc / wsum
        if score + 1e-12 < thr:
            failed = ev["failed_labels"]
            detail = "、".join(failed) if failed else f"加权{score:.2f}＜{thr:g}"
            return f"板块交叉未通过({detail})"
        return None

    # vote
    need = int(scc.get("min_pass_votes", 2) or 2)
    passes = int(ev["pass_count"])
    if passes >= max(1, need):
        return None
    failed = ev["failed_labels"]
    detail = "、".join(failed) if failed else f"{passes}/{n_ev}票"
    return f"板块交叉未通过({detail})"
