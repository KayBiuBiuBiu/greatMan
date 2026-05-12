"""启动前配置自检：在 JSON Schema 之后补充路径、邮件与数据目录等软性检查。

致命问题（errors）会阻止进入监控循环；告警（warnings）仅打印stderr。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from external_ml_features import EXTERNAL_FLOW_FEATURE_KEYS


def run_startup_config_checks(
    cfg: dict[str, Any],
    *,
    root: Path,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    def _resolve(p: str) -> Path:
        pp = Path(p.strip())
        return pp.resolve() if pp.is_absolute() else (root / pp).resolve()

    try:
        total = float((cfg.get("capital") or {}).get("total", 0) or 0)
        if total <= 0:
            warnings.append(
                "capital.total 未设或不大于 0，部分仓位/风控展示可能异常。"
            )
    except (TypeError, ValueError):
        warnings.append("capital.total 不是有效数值。")

    mf = cfg.get("ml_filter") or {}
    if bool(mf.get("enabled")):
        mp = str(mf.get("model_path") or "").strip()
        if mp:
            pp = _resolve(mp)
            if not pp.is_file():
                warnings.append(
                    f"朴素贝叶斯模型文件不存在（若从未训练可忽略）：{pp}"
                )
            elif bool(mf.get("external_flow_features_enabled")):
                try:
                    raw_m = json.loads(pp.read_text(encoding="utf-8"))
                    feats_m = raw_m.get("features") if isinstance(raw_m, dict) else None
                    n_m = len(feats_m) if isinstance(feats_m, list) else 0
                    expect_nb = 6 + len(EXTERNAL_FLOW_FEATURE_KEYS)
                    if n_m > 0 and n_m < expect_nb:
                        warnings.append(
                            f"已开启 external_flow_features，但 NB 模型仅 {n_m} 维特征（"
                            f"期望 {expect_nb} 维：基础 6 + ext {len(EXTERNAL_FLOW_FEATURE_KEYS)}）。"
                            f"请先跑 backtest_alerts 补全 hit，再执行："
                            f"python ml_train.py -c config.json"
                        )
                except (OSError, json.JSONDecodeError):
                    pass
    if bool(mf.get("kline_rf_enabled")):
        kp = str(mf.get("kline_rf_model_path") or "").strip()
        if kp:
            rk = _resolve(kp)
            if not rk.is_file():
                warnings.append(
                    f"kline_rf 模型文件不存在，该路 ML 将无法生效：{rk}"
                )
        db_rf = str(mf.get("kline_rf_db_path") or "").strip()
        if db_rf:
            dp = _resolve(db_rf)
            if not dp.is_file():
                warnings.append(
                    f"kline_rf 数据库不存在（训练/推断可能失败）：{dp}"
                )

    ks = cfg.get("kline_store") or {}
    if bool(ks.get("enabled")):
        dbp = str(ks.get("db_path") or "").strip()
        if dbp:
            dp = _resolve(dbp).parent
            try:
                dp.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                errors.append(f"kline_store.db_path 父目录不可写，无法 mkdir：{dp} ({e})")

    al = cfg.get("alert_log") or {}
    if bool(al.get("enabled")):
        try:
            from alert_log_store import resolve_alert_db_path

            adb = resolve_alert_db_path(cfg, root)
            if adb is not None:
                try:
                    adb.parent.mkdir(parents=True, exist_ok=True)
                    if adb.exists() and not os.access(adb, os.W_OK):
                        errors.append(f"alert_log 数据库存在但不可写：{adb}")
                except OSError as e:
                    errors.append(
                        f"alert_log 数据库目录不可创建或不可访问：{adb.parent} ({e})"
                    )
        except Exception as ex:
            warnings.append(f"无法解析 alert_log 数据库路径：{ex}")

    oa = cfg.get("ops_automation") or {}
    eb = cfg.get("email_command_bot") or {}
    nt = cfg.get("notifications") or {}
    ch = str((nt.get("remote_channel") if isinstance(nt, dict) else "") or "email").strip().lower()
    wc = (nt.get("wecom_webhook") or {}) if isinstance(nt, dict) else {}
    wc_url = str(wc.get("webhook_url") or "").strip() if isinstance(wc, dict) else ""
    needs_mail = bool(oa.get("auto_tune_email")) or bool(eb.get("enabled"))
    if needs_mail and ch in ("email", "both"):
        try:
            from email_notify import _load_mail_cfg

            if _load_mail_cfg() is None:
                warnings.append(
                    "已开启收盘调参邮件或邮件指令机器人，且 remote_channel 含 email，"
                    "但未检测到可用的 mail_config.json 或 MAIL_* 环境变量 SMTP 配置。"
                )
        except Exception as ex:
            warnings.append(f"检查邮件配置时异常（可忽略）：{ex}")
    if ch in ("wecom", "both") and isinstance(wc, dict) and bool(wc.get("enabled", True)):
        if not wc_url and not os.environ.get("WEWORK_WEBHOOK_URL", "").strip():
            warnings.append(
                "notifications.remote_channel 含 wecom，但未配置 wecom_webhook.webhook_url "
                "或环境变量 WEWORK_WEBHOOK_URL。"
            )

    dh = cfg.get("data_health") or {}
    hp = str(dh.get("heartbeat_path") or "").strip()
    if hp:
        try:
            hpath = _resolve(hp).parent
            hpath.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"data_health.heartbeat_path 父目录不可写：{e}")

    rh = cfg.get("realtime_hub") or {}
    if bool(rh.get("enabled")) and bool(rh.get("ws_enabled", True)):
        wt = str(rh.get("ws_transport") or "").strip().lower()
        if not wt:
            warnings.append(
                "realtime_hub.ws_enabled 为真但 ws_transport / ws_url 未配置为可用 WebSocket；"
                "东财 SSE 已移除，纯 HTTP 轮询请关 ws_enabled 或填写 ws_url + ws_transport=websocket。"
            )

    try:
        from sector_em import sector_index_cache_path

        scache = sector_index_cache_path(cfg, root)
        sdir = scache.parent
        try:
            sdir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(
                f"sector_em 行业缓存目录不可创建（无法写入 sector_index_cache.json）：{sdir} ({e})"
            )
        else:
            probe = sdir / ".sector_cache_write_probe"
            try:
                probe.write_text("", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except OSError as e:
                errors.append(
                    f"sector_index_cache.json 所在目录不可写：{sdir} ({e})"
                )
            if scache.exists() and not os.access(scache, os.W_OK):
                errors.append(f"行业缓存文件已存在但不可写：{scache}")
    except Exception as ex:
        warnings.append(f"检查行业缓存路径时异常：{ex}")

    return errors, warnings


def format_startup_report(errors: list[str], warnings: list[str]) -> str:
    lines: list[str] = []
    if errors:
        lines.append("[config] 启动自检未通过（请修正后再运行）：")
        for x in errors:
            lines.append(f"  ❌ {x}")
    if warnings:
        lines.append("[config] 启动自检告警（可不中断）：")
        for x in warnings:
            lines.append(f"  ⚠️ {x}")
    if not errors and not warnings:
        lines.append("[config] 启动自检通过（无额外告警）。")
    return "\n".join(lines)
