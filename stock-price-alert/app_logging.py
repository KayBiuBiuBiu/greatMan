"""可选结构化文件日志（P2-3）：RotatingFileHandler + JSON 行。"""

from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class _JsonLineFormatter(logging.Formatter):
    """每条日志一行 JSON；extra 中的简单标量会并入顶层。"""

    def __init__(self, datefmt: str | None = None) -> None:
        super().__init__(datefmt=datefmt)

    _EXTRA_KEYS = (
        "event",
        "code",
        "bk",
        "url",
        "duration_ms",
        "host",
        "consecutive_fails",
        "status_code",
        "section",
        "rk",
        "fails",
        "attempted",
        "weak_pillars",
        "weak_dims",
        "sector_data_incomplete",
        "sector_data_warning",
        "skipped_by_filter",
    )

    def format(self, record: logging.LogRecord) -> str:
        d: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            d["exc_info"] = self.formatException(record.exc_info)
        for k in self._EXTRA_KEYS:
            if hasattr(record, k):
                v = getattr(record, k)
                if v is not None:
                    d[k] = v
        dh = getattr(record, "degraded_hosts", None)
        if dh is not None:
            d["degraded_hosts"] = dh
        m = getattr(record, "metrics", None)
        if isinstance(m, dict) and m:
            d["metrics"] = m
        return json.dumps(d, ensure_ascii=False)


_ALERT_LOGGER = "run_alert"


def setup_app_logging(cfg: dict[str, Any], *, root: Path) -> logging.Logger:
    """
    读取 cfg['logging']：enabled / file / max_bytes / backup_count / level。
    未启用时仅返回 logger，不挂载文件 Handler。
    """
    log = logging.getLogger(_ALERT_LOGGER)
    raw = cfg.get("logging") or {}
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        log.handlers.clear()
        log.addHandler(logging.NullHandler())
        log.setLevel(logging.WARNING)
        log.propagate = False
        return log

    level_name = str(raw.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    rel = str(raw.get("file", "logs/run_alert.jsonl")).strip()
    path = Path(rel)
    if not path.is_absolute():
        path = (root / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = max(100_000, int(raw.get("max_bytes", 5_000_000)))
    backup = max(1, int(raw.get("backup_count", 3)))

    log.handlers.clear()
    fh = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup,
        encoding="utf-8",
    )
    fh.setFormatter(_JsonLineFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    fh.setLevel(level)
    log.addHandler(fh)

    if bool(raw.get("console_mirror", False)):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        sh.setLevel(level)
        log.addHandler(sh)

    log.setLevel(level)
    log.propagate = False
    return log


def get_alert_logger() -> logging.Logger:
    return logging.getLogger(_ALERT_LOGGER)


def has_jsonl_file_handler(log: logging.Logger | None = None) -> bool:
    """是否已挂载 JSONL 轮转文件（与 setup_app_logging 启用态一致）。"""
    lg = log or get_alert_logger()
    return any(isinstance(h, RotatingFileHandler) for h in lg.handlers)


def record_alert_event(
    level: int,
    msg: str,
    *,
    event: str,
    code: str | None = None,
    rk: str | None = None,
    duration_ms: float | None = None,
    section: str | None = None,
    fails: int | None = None,
    attempted: int | None = None,
    degraded_hosts: list[dict[str, Any]] | None = None,
    weak_pillars: dict[str, Any] | None = None,
    weak_dims: dict[str, Any] | None = None,
    sector_data_incomplete: bool | None = None,
    sector_data_warning: str | None = None,
    skipped_by_filter: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """控制台外的结构化行：仅在 JSONL 启用时写入。"""
    if not has_jsonl_file_handler():
        return
    lg = get_alert_logger()
    extra: dict[str, Any] = {"event": event}
    if code is not None:
        extra["code"] = code
    if rk is not None:
        extra["rk"] = rk
    if duration_ms is not None:
        extra["duration_ms"] = round(float(duration_ms), 3)
    if section is not None:
        extra["section"] = section
    if fails is not None:
        extra["fails"] = fails
    if attempted is not None:
        extra["attempted"] = attempted
    if degraded_hosts is not None:
        extra["degraded_hosts"] = degraded_hosts
    if weak_pillars is not None:
        extra["weak_pillars"] = weak_pillars
    if weak_dims is not None:
        extra["weak_dims"] = weak_dims
    if sector_data_incomplete is not None:
        extra["sector_data_incomplete"] = sector_data_incomplete
    if sector_data_warning is not None and str(sector_data_warning).strip() != "":
        extra["sector_data_warning"] = str(sector_data_warning).strip()
    if skipped_by_filter is not None and str(skipped_by_filter).strip() != "":
        extra["skipped_by_filter"] = str(skipped_by_filter).strip()
    if isinstance(metrics, dict) and metrics:
        extra["metrics"] = metrics
    lg.log(level, msg, extra=extra)


def emit_select_tool_line(msg: str, *, event: str, section: str) -> None:
    """选股 / 扫描 / quant_cli：始终打印 stdout；若已启用 JSONL 则追加一行结构化日志。"""
    print(msg, file=sys.stdout, flush=True)
    record_alert_event(logging.INFO, msg, event=event, section=section)
