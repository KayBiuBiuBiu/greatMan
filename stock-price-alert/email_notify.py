"""远程提醒：SMTP 邮件 + 企业微信群机器人 Webhook。

敏感信息：mail_config.json（已 gitignore）、环境变量 MAIL_*、或 notifications.wecom_webhook.webhook_url。
"""

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
from wecom_webhook import send_wecom_robot_message

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


def _remote_notify_settings(
    app_cfg: dict[str, Any] | None,
) -> tuple[str, str, str, bool]:
    """
    返回 (remote_channel, wecom_url, wecom_msgtype, wecom_enabled)。
    remote_channel: email | wecom | both | none
    """
    nt: dict[str, Any] = {}
    if isinstance(app_cfg, dict):
        raw_nt = app_cfg.get("notifications")
        if isinstance(raw_nt, dict):
            nt = raw_nt
    ch = str(nt.get("remote_channel") or "email").strip().lower()
    if ch not in ("email", "wecom", "both", "none"):
        ch = "email"
    wc_box = nt.get("wecom_webhook")
    if not isinstance(wc_box, dict):
        wc_box = {}
    url = str(wc_box.get("webhook_url") or "").strip()
    if not url:
        url = os.environ.get("WEWORK_WEBHOOK_URL", "").strip()
    msgtype = str(wc_box.get("msgtype") or "markdown").strip().lower()
    if msgtype not in ("text", "markdown"):
        msgtype = "markdown"
    wc_en = bool(wc_box.get("enabled", True))
    return ch, url, msgtype, wc_en


def _send_smtp_alert(
    subject: str,
    body: str,
) -> bool:
    cfg = _load_mail_cfg()
    if cfg is None:
        return False
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


def send_email_alert(
    subject: str,
    content: str,
    *,
    append_disclaimer: bool = True,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    """
    按 config.notifications.remote_channel 投递：email / wecom / both / none。
    与历史行为兼容：未配置 notifications 时等同仅 email。
    """
    ch, wc_url, wc_msgtype, wc_en = _remote_notify_settings(app_cfg)
    if ch == "none":
        return False
    body = (
        append_to_body(content, cfg=app_cfg)
        if append_disclaimer
        else content
    )
    ok = False
    if ch in ("email", "both"):
        ok = _send_smtp_alert(subject, body) or ok
    if ch in ("wecom", "both") and wc_en and wc_url:
        ok = (
            send_wecom_robot_message(
                wc_url,
                wc_msgtype,
                subject,
                body,
            )
            or ok
        )
    return ok


def send_buy_signal_email(
    subject: str,
    body: str,
    *,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    """买入类远程提醒（邮件/企微由配置决定）。"""
    return send_email_alert(subject, body, app_cfg=app_cfg)


def send_sell_signal_email(
    subject: str,
    body: str,
    *,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    """卖出类远程提醒（邮件/企微由配置决定）。"""
    return send_email_alert(subject, body, app_cfg=app_cfg)


def send_wecom_only_alert(
    subject: str,
    content: str,
    *,
    app_cfg: dict[str, Any] | None = None,
) -> bool:
    """仅发企业微信机器人（不受 remote_channel 限制）。"""
    _, wc_url, wc_msgtype, wc_en = _remote_notify_settings(app_cfg)
    if not wc_en or not wc_url:
        return False
    return send_wecom_robot_message(wc_url, wc_msgtype, subject, content)


if __name__ == "__main__":
    import sys

    ok = send_email_alert(
        "【测试】股票邮件提醒",
        "若收到本邮件，说明 mail_config.json 或环境变量已配置成功。",
        append_disclaimer=False,
    )
    print("发送成功" if ok else "未配置或发送失败（请检查 mail_config / 网络 / 授权码）")
    raise SystemExit(0 if ok else 1)
