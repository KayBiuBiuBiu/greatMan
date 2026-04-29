#!/usr/bin/env python3
"""SMTP 测试：账号与授权码仅放在 mail_config.json（已 gitignore），勿写进本文件。"""

from __future__ import annotations

import json
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_MAIL = ROOT / "mail_config.json"

SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 465


def _load_local_mail() -> tuple[str, str, list[str]]:
    if not _MAIL.exists():
        return "", "", []
    try:
        j = json.loads(_MAIL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", "", []
    sender = str(j.get("sender") or "").strip()
    auth = str(j.get("password") or "").strip()
    rec = j.get("receivers")
    if isinstance(rec, list):
        receivers = [str(x).strip() for x in rec if str(x).strip()]
    else:
        receivers = [
            x.strip() for x in str(rec or "").split(",") if x.strip()
        ]
    return sender, auth, receivers


def send_stock_mail(title: str, content: str) -> bool:
    sender, auth, receivers = _load_local_mail()
    if not sender or not auth or not receivers:
        print(
            "❌ 缺少 mail_config.json 或未填写 sender/password/receivers\n"
            "   请在本目录创建该文件（可参考 mail_config.example.json）"
        )
        return False

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = Header(title, "utf-8")
    msg.attach(MIMEText(content, "plain", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(sender, auth)
        server.sendmail(sender, receivers, msg.as_string())
        server.quit()
        print("✅ 邮件发送成功！！！")
        return True
    except Exception as e:
        print(f"❌ 发送失败：{e}")
        return False


if __name__ == "__main__":
    send_stock_mail(
        "【股票提醒】测试成功",
        "你的邮件提醒配置完成！以后买入信号会自动发到这里！",
    )
