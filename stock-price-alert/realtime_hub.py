"""阶段三·推送演进：HTTP 轮询 + 可选东财 SSE 推送 / 自定义 WebSocket。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, time as dt_time
from typing import Any

# 尾盘差值特征：保留约 30 分钟内的报价 (monotonic_ts, price)
_TAIL_WINDOW_SEC = 1800.0
_TAIL_MIN_SPAN_SEC = 1700.0
_TAIL_HIST_MAX = 4000

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

from eastmoney_sse_quotes import (
    DEFAULT_FIELDS as EM_SSE_DEFAULT_FIELDS,
    DEFAULT_SSE_URL as EM_SSE_DEFAULT_URL,
    start_sse_partition_threads,
)
from quote_eastmoney import fetch_quote_metrics

_log = logging.getLogger("realtime_hub")


def _ws_client_available() -> bool:
    try:
        import websocket  # noqa: F401

        return True
    except ImportError:
        return False


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _cn_datetime_now() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:
            pass
    return datetime.now()


def _infer_pre_close(price: float, change_pct: float | None) -> float:
    if price <= 0 or change_pct is None:
        return 0.0
    try:
        d = 1.0 + float(change_pct) / 100.0
    except (TypeError, ValueError):
        return 0.0
    if abs(d) < 1e-12:
        return 0.0
    return round(price / d, 6)


def _em_price_from_f43(v: Any) -> float | None:
    """部分 JSON 推送里 f43 为价格×100（整数）。"""
    x = _to_float(v, 0.0)
    if x <= 0:
        return None
    return round(x / 100.0, 3)


class RealtimeQuoteHub:
    """
    后台线程按固定间隔批量拉取 watchlist 行情，写入线程安全缓存；
    可选：东财 SSE 分区线程（真推送）或自定义 ws_url 的 WebSocketApp。
    """

    def __init__(
        self,
        *,
        poll_interval_sec: float,
        ut: str,
        max_workers_hint: int = 3,
        start_offset_sec: float = 0.0,
        ws_url: str = "",
        ws_reconnect_sec: float = 5.0,
        ws_ping_interval_sec: float = 30.0,
        ws_transport: str = "",
        em_sse_url: str = "",
        em_sse_fields: str = "",
        em_sse_slots: int = 4,
        em_sse_burst_sec: float = 12.0,
        em_sse_read_timeout_sec: float = 60.0,
        push_stream_enabled: bool = True,
    ) -> None:
        self._poll = max(1.0, float(poll_interval_sec))
        self._start_offset = max(0.0, float(start_offset_sec))
        self._ut = ut
        self._sem = threading.Semaphore(max(1, int(max_workers_hint)))
        self._lock = threading.Lock()
        self._quotes: dict[tuple[str, str], dict[str, Any]] = {}
        # 交易日历日内增量统计（随报价更新；供 intraday_position / morning_ret 等 O(1) 读取）
        self._day_agg: dict[tuple[str, str], dict[str, Any]] = {}
        self._price_hist: dict[tuple[str, str], deque[tuple[float, float]]] = {}
        self._watch_rules: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_url = str(ws_url or "").strip()
        self._ws_reconnect = max(1.0, float(ws_reconnect_sec))
        self._ws_ping = max(5.0, float(ws_ping_interval_sec))
        self._ws_transport = str(ws_transport or "").strip().lower()
        self._em_sse_url = str(em_sse_url or "").strip()
        self._em_sse_fields = str(em_sse_fields or "").strip()
        self._em_sse_slots = max(1, int(em_sse_slots))
        self._em_sse_burst = max(2.0, float(em_sse_burst_sec))
        self._em_sse_read_to = max(15.0, float(em_sse_read_timeout_sec))
        self._sse_threads: list[threading.Thread] = []
        self._push_stream_enabled = bool(push_stream_enabled)

    def set_watch_rules(self, rules: list[dict[str, Any]]) -> None:
        with self._lock:
            self._watch_rules = list(rules or [])

    def _snap_rules(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._watch_rules)

    def _bump_day_agg_unlocked(
        self,
        code: str,
        market: str,
        q: dict[str, Any],
        *,
        price: float,
    ) -> None:
        """在已持有 self._lock 下调用：用本轮报价更新当日高低、开盘代理、上午收盘涨跌幅快照。"""
        if price <= 0:
            return
        key = (code, market)
        now = _cn_datetime_now()
        today = now.date().isoformat()
        naive = now.replace(tzinfo=None) if now.tzinfo else now
        cmp_t = naive.time()

        chg_raw = q.get("change_pct")
        chg: float | None
        try:
            chg = float(chg_raw) if chg_raw is not None else None
        except (TypeError, ValueError):
            chg = None

        q_pre = _to_float(q.get("pre_close"), 0.0)
        q_open = _to_float(q.get("open"), 0.0)
        q_hi = _to_float(q.get("high"), 0.0)
        q_lo = _to_float(q.get("low"), 0.0)

        agg = self._day_agg.get(key)
        if not agg or agg.get("trade_date") != today:
            self._price_hist[key] = deque(maxlen=_TAIL_HIST_MAX)
            pre_close = q_pre if q_pre > 0 else _infer_pre_close(price, chg)
            open_px = q_open if q_open > 0 else price
            hi0 = max(q_hi, open_px, price) if q_hi > 0 else max(open_px, price)
            lo0 = min(q_lo, open_px, price) if q_lo > 0 else min(open_px, price)
            self._day_agg[key] = {
                "trade_date": today,
                "open_price": round(open_px, 6),
                "high_price": round(hi0, 6),
                "low_price": round(lo0, 6),
                "pre_close": round(pre_close, 6) if pre_close > 0 else 0.0,
                "morning_ret": None,
                "morning_done": False,
            }
            agg = self._day_agg[key]
        else:
            if q_pre > 0:
                agg["pre_close"] = round(q_pre, 6)
            elif agg.get("pre_close", 0.0) <= 0 and chg is not None:
                pc2 = _infer_pre_close(price, chg)
                if pc2 > 0:
                    agg["pre_close"] = pc2
            if q_open > 0:
                agg["open_price"] = round(q_open, 6)
            if q_hi > 0:
                agg["high_price"] = round(max(float(agg["high_price"]), q_hi, price), 6)
            else:
                agg["high_price"] = round(max(float(agg["high_price"]), price), 6)
            if q_lo > 0:
                agg["low_price"] = round(min(float(agg["low_price"]), q_lo, price), 6)
            else:
                agg["low_price"] = round(min(float(agg["low_price"]), price), 6)

        if not agg.get("morning_done"):
            # 仅在上午收盘后、午休前窗口内快照，避免午后首次报价冒充「上午涨跌幅」
            if dt_time(11, 30) <= cmp_t < dt_time(12, 0):
                if chg is not None:
                    agg["morning_ret"] = round(float(chg), 6)
                elif float(agg.get("pre_close") or 0.0) > 0:
                    pc = float(agg["pre_close"])
                    agg["morning_ret"] = round((price - pc) / pc * 100.0, 6)
                agg["morning_done"] = True
            elif cmp_t >= dt_time(13, 0):
                agg["morning_done"] = True

        hist = self._price_hist.setdefault(
            key, deque(maxlen=_TAIL_HIST_MAX)
        )
        now_m = time.monotonic()
        hist.append((now_m, price))
        while hist and hist[0][0] < now_m - _TAIL_WINDOW_SEC:
            hist.popleft()

    def get_intraday_snapshot(
        self,
        code: str,
        market: str,
        *,
        price: float,
        change_pct: float | None = None,
    ) -> dict[str, Any]:
        """
        基于 Hub 内当日增量状态与给定现价，计算日内特征（不发起 HTTP）。
        差值法：afternoon_strength_diff = 全日相对昨收涨跌 − 上午快照涨跌；
        tail_vs_body_diff = 近窗口末段涨跌幅 − 此前「开盘→窗口起点」涨跌幅。
        若尚无聚合则返回空 dict。
        """
        m = str(market or "sh").strip().lower()
        c = str(code).strip().zfill(6) if str(code).strip().isdigit() else str(code).strip()
        key = (c, m)
        with self._lock:
            agg = self._day_agg.get(key)
            if not agg or price <= 0:
                return {}
            op = float(agg.get("open_price") or 0.0)
            hi = float(agg.get("high_price") or 0.0)
            lo = float(agg.get("low_price") or 0.0)
            morning_ret = agg.get("morning_ret")
            pre_close = float(agg.get("pre_close") or 0.0)

            hist = self._price_hist.get(key)
            p_tail_ref: float | None = None
            if hist:
                now_mono = time.monotonic()
                while hist and hist[0][0] < now_mono - _TAIL_WINDOW_SEC:
                    hist.popleft()
                if (
                    hist
                    and (now_mono - hist[0][0]) >= _TAIL_MIN_SPAN_SEC
                ):
                    p_tail_ref = float(hist[0][1])

        since_open: float | None = None
        if op > 0:
            since_open = round((price - op) / op * 100.0, 6)

        span = hi - lo
        if span > 1e-9:
            intraday_position = (price - lo) / span
        else:
            intraday_position = 0.5
        intraday_position = max(0.0, min(1.0, round(float(intraday_position), 6)))

        full_day_ret: float | None = None
        if change_pct is not None:
            try:
                full_day_ret = float(change_pct)
            except (TypeError, ValueError):
                full_day_ret = None
        if full_day_ret is None and pre_close > 0:
            full_day_ret = round((price - pre_close) / pre_close * 100.0, 6)

        afternoon_strength_diff: float | None = None
        if (
            morning_ret is not None
            and full_day_ret is not None
        ):
            try:
                afternoon_strength_diff = round(
                    float(full_day_ret) - float(morning_ret), 6
                )
            except (TypeError, ValueError):
                afternoon_strength_diff = None

        # 自日内最高价回落的「百分点」差：(H-P)/昨收×100，与 intraday_position 不同量纲
        pullback_from_high_pts: float | None = None
        if pre_close > 0 and hi > 0:
            pullback_from_high_pts = round(
                (hi - price) / pre_close * 100.0, 6
            )

        tail_vs_body_diff: float | None = None
        if (
            p_tail_ref is not None
            and p_tail_ref > 0
            and op > 0
        ):
            r_tail = (price - p_tail_ref) / p_tail_ref * 100.0
            r_body = (p_tail_ref - op) / op * 100.0
            tail_vs_body_diff = round(r_tail - r_body, 6)

        out: dict[str, Any] = {
            "open_price": op,
            "high_price": hi,
            "low_price": lo,
            "since_open_pct": since_open,
            "intraday_position": intraday_position,
            "morning_ret": morning_ret,
            "pre_close_intraday": pre_close if pre_close > 0 else None,
            "afternoon_strength_diff": afternoon_strength_diff,
            "pullback_from_high_pts": pullback_from_high_pts,
            "tail_vs_body_diff": tail_vs_body_diff,
        }
        return out

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="RealtimeQuoteHub", daemon=True)
        self._thread.start()

        use_sse = self._push_stream_enabled and self._ws_transport in (
            "eastmoney_sse",
            "em_sse",
            "sse",
        )
        use_ws = (
            self._push_stream_enabled
            and self._ws_url
            and self._ws_transport in ("", "websocket", "ws")
            and _ws_client_available()
        )

        if use_sse:
            base = self._em_sse_url or EM_SSE_DEFAULT_URL
            fields = self._em_sse_fields or EM_SSE_DEFAULT_FIELDS

            def _on(m: dict[str, Any]) -> None:
                c = str(m.get("code") or "").strip().zfill(6)
                mk = str(m.get("market") or "sh").strip().lower()
                if "market" not in m or mk not in ("sh", "sz"):
                    mk = "sh"
                self._merge_quote(c, mk, m)

            self._sse_threads = start_sse_partition_threads(
                get_rules=self._snap_rules,
                n_slots=self._em_sse_slots,
                ut=self._ut,
                base_url=base,
                fields=fields,
                stop=self._stop,
                on_metrics=_on,
                reconnect_sec=self._ws_reconnect,
                burst_sec=self._em_sse_burst,
                read_timeout_sec=self._em_sse_read_to,
            )
            _log.info(
                "realtime hub: eastmoney SSE 已启动 slots=%s burst=%ss",
                self._em_sse_slots,
                self._em_sse_burst,
            )
        elif use_ws:
            self._ws_thread = threading.Thread(
                target=self._run_ws_loop, name="RealtimeQuoteHubWS", daemon=True
            )
            self._ws_thread.start()
        elif self._ws_url and not _ws_client_available():
            _log.warning(
                "realtime_hub.ws_url 已配置但未安装 websocket-client，跳过 WS（pip install websocket-client）"
            )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._poll + 2.0)
            self._thread = None
        for t in self._sse_threads:
            t.join(timeout=2.0)
        self._sse_threads.clear()
        if self._ws_thread:
            self._ws_thread.join(timeout=5.0)
            self._ws_thread = None

    def get_metrics(self, code: str, market: str) -> dict[str, Any] | None:
        m = str(market or "sh").strip().lower()
        c = str(code).strip().zfill(6) if str(code).strip().isdigit() else str(code).strip()
        key = (c, m)
        with self._lock:
            q = self._quotes.get(key)
            if not isinstance(q, dict):
                return None
            out = dict(q)
            px = _to_float(out.get("price"), 0.0)
        if px > 0:
            chg_snap: float | None = None
            cr = out.get("change_pct")
            if cr is not None:
                try:
                    chg_snap = float(cr)
                except (TypeError, ValueError):
                    chg_snap = None
            snap = self.get_intraday_snapshot(
                c, m, price=px, change_pct=chg_snap
            )
            for k, v in snap.items():
                if v is not None:
                    out[k] = v
        return out

    def wait_for_quote_coverage(
        self,
        *,
        timeout_sec: float = 12.0,
        min_fraction: float = 0.85,
        sleep_sec: float = 0.06,
    ) -> tuple[int, int]:
        """等待后台轮询线程把当前 watch 列表的现价写入缓存（缓解首轮全走 sina）。"""
        deadline = time.monotonic() + max(0.5, float(timeout_sec))
        last_ok, last_n = 0, 0
        min_fraction = max(0.05, min(1.0, float(min_fraction)))
        while time.monotonic() < deadline:
            rules = self._snap_rules()
            last_n = len(rules)
            if last_n == 0:
                return 0, 0
            ok = 0
            for rule in rules:
                code = str(rule.get("code") or "").strip()
                mk = str(rule.get("market") or "sh").strip().lower()
                if not code.isdigit():
                    continue
                code = code.zfill(6)
                if len(code) != 6:
                    continue
                q = self.get_metrics(code, mk)
                if q and float(q.get("price") or 0.0) > 0.0:
                    ok += 1
            last_ok = ok
            if ok / last_n >= min_fraction:
                return ok, last_n
            time.sleep(max(0.02, float(sleep_sec)))
        return last_ok, last_n

    def _merge_quote(self, code: str, market: str, q: dict[str, Any]) -> None:
        code = str(code).strip().zfill(6) if str(code).strip().isdigit() else str(code).strip()
        market = str(market or "sh").strip().lower()
        with self._lock:
            self._quotes[(code, market)] = q
            px = _to_float(q.get("price"), 0.0)
            self._bump_day_agg_unlocked(code, market, q, price=px)

    def _ingest_ws_obj(self, obj: Any) -> None:
        if isinstance(obj, list):
            for it in obj:
                self._ingest_ws_obj(it)
            return
        if not isinstance(obj, dict):
            return
        for k in ("data", "diff", "full", "quotes"):
            sub = obj.get(k)
            if isinstance(sub, (list, dict)):
                self._ingest_ws_obj(sub)
        code_raw = str(obj.get("f12") or obj.get("code") or "").strip()
        if not code_raw.isdigit():
            return
        code = code_raw.zfill(6)
        if len(code) != 6:
            return
        mraw = obj.get("f13")
        if mraw is not None:
            mi = int(_to_float(mraw, -1))
            market = "sh" if mi == 1 else "sz" if mi == 0 else ""
        else:
            market = str(obj.get("market") or "sh").strip().lower()
        if market not in ("sh", "sz"):
            market = "sh"
        if "f43" in obj and obj.get("f43") is not None:
            price = _em_price_from_f43(obj.get("f43"))
        else:
            price = _to_float(
                obj.get("price") or obj.get("last") or obj.get("current"), 0.0
            )
            if price > 0:
                price = round(price, 3)
            else:
                price = None
        if not price or price <= 0:
            return
        chg: float | None = None
        if obj.get("f170") is not None:
            chg = round(_to_float(obj.get("f170"), 0.0) / 100.0, 4)
        elif obj.get("change_pct") is not None:
            chg = _to_float(obj.get("change_pct"), 0.0)
        name = str(obj.get("f14") or obj.get("name") or "")
        q: dict[str, Any] = {
            "code": code,
            "name": name,
            "price": price,
            "change_pct": chg,
            "amount_yuan": _to_float(obj.get("amount_yuan"), 0.0),
            "float_mv_yuan": _to_float(obj.get("float_mv_yuan"), 0.0),
            "total_mv_yuan": _to_float(obj.get("total_mv_yuan"), 0.0),
            "price_source": "websocket",
        }
        self._merge_quote(code, market, q)

    def _ingest_ws_text(self, message: str | bytes) -> None:
        if isinstance(message, (bytes, bytearray)):
            try:
                text = message.decode("utf-8", errors="replace")
            except Exception:
                return
        else:
            text = str(message)
        text = text.strip()
        if not text:
            return
        for part in text.split("\n"):
            part = part.strip()
            if not part:
                continue
            try:
                self._ingest_ws_obj(json.loads(part))
            except json.JSONDecodeError:
                continue

    def _run_ws_loop(self) -> None:
        import websocket

        while not self._stop.is_set():
            try:

                def on_message(_ws: Any, msg: str | bytes) -> None:
                    self._ingest_ws_text(msg)

                def on_error(_ws: Any, err: Any) -> None:
                    if err:
                        _log.debug("realtime hub WS error: %s", err)

                def on_open(_ws: Any) -> None:
                    _log.info("realtime hub WebSocket connected")

                def on_close(_ws: Any, *_a: Any) -> None:
                    _log.info("realtime hub WebSocket closed")

                ws = websocket.WebSocketApp(
                    self._ws_url,
                    on_message=on_message,
                    on_error=on_error,
                    on_open=on_open,
                    on_close=on_close,
                )
                ws.run_forever(ping_interval=self._ws_ping, ping_timeout=15)
            except Exception as e:
                _log.warning("realtime hub WS run_forever: %s", e)
            if self._stop.wait(timeout=self._ws_reconnect):
                return

    def _run(self) -> None:
        if self._start_offset > 0.0 and self._stop.wait(timeout=self._start_offset):
            return
        while not self._stop.is_set():
            with self._lock:
                batch = list(self._watch_rules)
            for rule in batch:
                if self._stop.is_set():
                    break
                code = str(rule.get("code") or "").strip()
                market = str(rule.get("market") or "sh").strip().lower()
                if not code.isdigit() or len(code) != 6:
                    continue
                code = code.zfill(6)
                try:
                    with self._sem:
                        qm = fetch_quote_metrics(code, market, ut=self._ut)
                    q = dict(qm)
                    q["code"] = code
                    self._merge_quote(code, market, q)
                except Exception:
                    continue
            self._stop.wait(timeout=self._poll)


def hub_from_cfg(cfg: dict[str, Any], *, ut: str) -> RealtimeQuoteHub | None:
    rh = cfg.get("realtime_hub") or {}
    if not isinstance(rh, dict) or not bool(rh.get("enabled")):
        return None
    perf = cfg.get("performance") or {}
    w = int(perf.get("fetch_max_concurrency", 3))
    off = float(perf.get("hub_poll_start_offset_sec", 0) or 0)
    ws_url = ""
    ws_transport = str(rh.get("ws_transport") or "").strip().lower()
    if bool(rh.get("ws_enabled")):
        if ws_transport not in ("eastmoney_sse", "em_sse", "sse"):
            ws_url = str(rh.get("ws_url") or "").strip()
    return RealtimeQuoteHub(
        poll_interval_sec=float(rh.get("poll_interval_sec", 5) or 5),
        ut=ut,
        max_workers_hint=max(1, w),
        start_offset_sec=off,
        ws_url=ws_url,
        ws_reconnect_sec=float(rh.get("ws_reconnect_sec", 5) or 5),
        ws_ping_interval_sec=float(rh.get("ws_ping_interval_sec", 30) or 30),
        ws_transport=ws_transport,
        em_sse_url=str(rh.get("em_sse_url") or "").strip(),
        em_sse_fields=str(rh.get("em_sse_fields") or "").strip(),
        em_sse_slots=int(rh.get("em_sse_slots", 4) or 4),
        em_sse_burst_sec=float(rh.get("em_sse_burst_sec", 12) or 12),
        em_sse_read_timeout_sec=float(rh.get("em_sse_read_timeout_sec", 60) or 60),
        push_stream_enabled=bool(rh.get("ws_enabled", True)),
    )


def ws_transport_enabled(cfg: dict[str, Any] | None) -> bool:
    """ws_enabled 时：东财 SSE 模式，或已填 ws_url 且已安装 websocket-client。"""
    rh = (cfg or {}).get("realtime_hub") or {}
    if not isinstance(rh, dict):
        return False
    if not bool(rh.get("ws_enabled")):
        return False
    wt = str(rh.get("ws_transport") or "").strip().lower()
    if wt in ("eastmoney_sse", "em_sse", "sse"):
        return True
    if str(rh.get("ws_url") or "").strip():
        return _ws_client_available()
    return False
