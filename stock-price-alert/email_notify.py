"""可选：SMTP 邮件提醒（买入信号等）。敏感信息放在 mail_config.json（已 gitignore）或环境变量。"""

from __future__ import annotations

import json
import os
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from legal_disclosure import append_to_body

ROOT = Path(__file__).resolve().parent
_MAIL_PATH = ROOT / "mail_config.json"


def _load_mail_cfg() -> dict[str, Any] | None:
    """环境变量优先，其次 mail_config.json。"""
    sender = os.environ.get("MAIL_SENDER", "").strip()
    password = os.environ.get("MAIL_PASSWORD", "").strip()
    server = os.environ.get("MAIL_SMTP_SERVER", "").strip()
    port_s = os.environ.get("MAIL_SMTP_PORT", "").strip()
    recv_s = os.environ.get("MAIL_RECEIVERS", "").strip()

    if sender and password and server and recv_s:
        receivers = [x.strip() for x in recv_s.split(",") if x.strip()]
        if receivers:
            out: dict[str, Any] = {
                "smtp_server": server,
                "smtp_port": int(port_s or "465"),
                "sender": sender,
                "password": password,
                "receivers": receivers,
            }
            imap_srv = os.environ.get("MAIL_IMAP_SERVER", "").strip()
            if imap_srv:
                out["imap_server"] = imap_srv
            imap_p = os.environ.get("MAIL_IMAP_PORT", "").strip()
            if imap_p:
                out["imap_port"] = int(imap_p)
            imap_f = os.environ.get("MAIL_IMAP_FOLDER", "").strip()
            if imap_f:
                out["imap_folder"] = imap_f
            return out

    if not _MAIL_PATH.exists():
        return None
    try:
        raw = json.loads(_MAIL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    sender = str(raw.get("sender") or "").strip()
    password = str(raw.get("password") or "").strip()
    server = str(raw.get("smtp_server") or "").strip()
    port = int(raw.get("smtp_port") or 465)
    rec = raw.get("receivers")
    if isinstance(rec, str):
        receivers = [x.strip() for x in rec.split(",") if x.strip()]
    elif isinstance(rec, list):
        receivers = [str(x).strip() for x in rec if str(x).strip()]
    else:
        receivers = []
    if not (sender and password and server and receivers):
        return None
    out2: dict[str, Any] = {
        "smtp_server": server,
        "smtp_port": port,
        "sender": sender,
        "password": password,
        "receivers": receivers,
    }
    imap_srv2 = str(raw.get("imap_server") or "").strip()
    if imap_srv2:
        out2["imap_server"] = imap_srv2
    if raw.get("imap_port") is not None:
        try:
            out2["imap_port"] = int(raw.get("imap_port"))
        except (TypeError, ValueError):
            pass
    imap_fold2 = str(raw.get("imap_folder") or "").strip()
    if imap_fold2:
        out2["imap_folder"] = imap_fold2
    return out2


def load_mail_config() -> dict[str, Any] | None:
    """与买卖提醒邮件相同的配置（mail_config.json / 环境变量），供 IMAP 指令机器人复用。"""
    return _load_mail_cfg()


def send_email_alert(
    subject: str,
    content: str,
    *,
    append_disclaimer: bool = True,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    cfg = _load_mail_cfg()
    if cfg is None:
        return False
    body = (
        append_to_body(content, cfg=app_cfg)
        if append_disclaimer
        else content
    )
    msg = MIMEMultipart()
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(cfg["receivers"])
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        server = smtplib.SMTP_SSL(cfg["smtp_server"], int(cfg["smtp_port"]))
        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receivers"], msg.as_string())
        server.quit()
        return True
    except Exception:
        return False


def send_buy_signal_email(
    subject: str,
    body: str,
    *,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    """已配置邮件时发送；未配置则静默跳过。"""
    if _load_mail_cfg() is None:
        return False
    return send_email_alert(subject, body, app_cfg=app_cfg)


def send_sell_signal_email(
    subject: str,
    body: str,
    *,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    """卖出信号邮件；逻辑与买入相同。"""
    if _load_mail_cfg() is None:
        return False
    return send_email_alert(subject, body, app_cfg=app_cfg)


if __name__ == "__main__":
    import sys

    ok = send_email_alert(
        "【测试】股票邮件提醒",
        "若收到本邮件，说明 mail_config.json 或环境变量已配置成功。",
        append_disclaimer=False,
    )
    print("发送成功" if ok else "未配置或发送失败（请检查 mail_config / 网络 / 授权码）")
    raise SystemExit(0 if ok else 1)
