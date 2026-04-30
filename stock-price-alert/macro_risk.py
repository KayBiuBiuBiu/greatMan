"""后台宏观/板块风控权重（仅参与打分降权，不单独前台展示）。"""

from __future__ import annotations

import threading
import time
from typing import Any

from utils import safe_get

_INDEX_KLINE_LOCK = threading.Lock()
_index_closes_ts: float = 0.0
_index_closes: list[float] | None = None
_index_kline_ttl_sec: float = 60.0
_SH_INDEX_UT = "fa5fd1943c7b386f172d6893dbfba10b"


def configure_index_kline_cache(ttl_sec: float | None = None) -> None:
    """加载 config 后由 run_alert 调用；上证日 K 在 TTL 内只拉一次，供情绪与 5 日收益共用。"""
    global _index_kline_ttl_sec
    if ttl_sec is not None:
        with _INDEX_KLINE_LOCK:
            _index_kline_ttl_sec = max(0.0, float(ttl_sec))


def _parse_closes_from_kline_json(j: dict[str, Any]) -> list[float] | None:
    klines = (j.get("data") or {}).get("klines") or []
    closes: list[float] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 3:
            try:
                closes.append(float(parts[2]))
            except ValueError:
                continue
    return closes if closes else None


def _fetch_sh_index_closes_network() -> list[float] | None:
    try:
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": "1.000001",
            "klt": "101",
            "fqt": "1",
            "lmt": "12",
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": _SH_INDEX_UT,
        }
        r = safe_get(url, params=params, timeout=10.0)
        if r is None:
            return None
        r.raise_for_status()
        j = r.json()
        return _parse_closes_from_kline_json(j)
    except Exception:
        return None


def get_sh_index_closes_cached() -> list[float] | None:
    """上证指数日 K 收盘价序列；带 TTL 的进程内缓存。"""
    global _index_closes_ts, _index_closes
    now = time.time()
    with _INDEX_KLINE_LOCK:
        if (
            _index_closes is not None
            and _index_kline_ttl_sec > 0
            and now - _index_closes_ts < _index_kline_ttl_sec
        ):
            return list(_index_closes)
        closes = _fetch_sh_index_closes_network()
        if closes:
            _index_closes = closes
            _index_closes_ts = time.time()
            return list(closes)
        _index_closes = None
        _index_closes_ts = 0.0
        return None


def _keyword_hit(text: str, keywords: tuple[str, ...]) -> bool:
    t = text or ""
    return any(k in t for k in keywords)


def industry_whitelist_bonus(industry: str, stock_name: str) -> bool:
    """消费、食品家电、高端制造、汽车零部件、风光储、新能源有色等。"""
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
        "机械设备",
        "通用设备",
        "专用设备",
        "自动化",
        "军工",
        "国防",
        "汽车零部件",
        "汽车零",
        "电机",
        "电池",
        "光伏",
        "风电",
        "储能",
        "电力设备",
        "能源金属",
        "小金属",
        "稀有金属",
        "稀土",
        "锂",
        "钴",
        "镍",
        "电网设备",
        "电机",
        "消费电子",
        "半导体",
        "通信",
        "光学光电子",
        "元件",
        "电子化学品",
    )
    return _keyword_hit(blob, keys)


def industry_blacklist_penalty(industry: str, stock_name: str) -> bool:
    """地产、基建、建材、金融、煤炭钢铁、传统化工等。"""
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
        "炼化",
        "银行",
        "保险",
        "证券",
        "多元金融",
        "化学原料",
        "化学制品",
        "农化制品",
        "塑料",
        "橡胶",
    )
    if _keyword_hit(blob, keys):
        return True
    # 低端有色：铝/铅/锡（名称或行业含关键字）
    metal_low = ("铝", "铅", "锡")
    if _keyword_hit(industry or "", metal_low) or _keyword_hit(stock_name or "", metal_low):
        if not _keyword_hit(blob, ("锂", "钴", "镍", "稀土", "能源金属", "稀土永磁")):
            return True
    return False


def fetch_index_5d_return() -> float | None:
    """上证指数近 5 个交易日累计涨跌比例 (close[-1]/close[-6]-1)，失败返回 None。"""
    try:
        closes = get_sh_index_closes_cached()
        if closes is None or len(closes) < 6:
            return None
        c0, c5 = closes[-1], closes[-6]
        if c5 <= 0:
            return None
        return float((c0 - c5) / c5)
    except Exception:
        return None


def fetch_index_mood_mult() -> float:
    """
    粗略大盘情绪：上证指数近 5 日涨跌。
    失败时返回 1.0，成功时 [-0.03,0.03] 映射到 [0.94,1.06] 乘子。
    """
    try:
        closes = get_sh_index_closes_cached()
        if closes is None or len(closes) < 6:
            return 1.0
        c0, c5 = closes[-1], closes[-6]
        if c5 <= 0:
            return 1.0
        ret5 = (c0 - c5) / c5
        m = 1.0 + max(-0.06, min(0.06, ret5))
        return float(max(0.94, min(1.06, m)))
    except Exception:
        return 1.0


def macro_score_multiplier(
    industry: str,
    stock_name: str,
    *,
    index_mood_mult: float | None = None,
    cfg: dict[str, Any] | None = None,
) -> float:
    """
    后台综合乘子：利好赛道略加成，利空板块降权；叠加大盘情绪。
    不在控制台单独展示，仅作用于排序分。
    """
    cfg = cfg or {}
    base = 1.0
    if industry_whitelist_bonus(industry, stock_name):
        base *= 1.06
    if industry_blacklist_penalty(industry, stock_name):
        base *= 0.72

    mood_ov = float((cfg.get("macro_risk") or {}).get("index_mood_mult_override") or 0.0)
    if mood_ov > 0:
        base *= mood_ov
    elif index_mood_mult is not None:
        base *= float(index_mood_mult)
    else:
        base *= fetch_index_mood_mult()

    return float(max(0.55, min(1.25, base)))
