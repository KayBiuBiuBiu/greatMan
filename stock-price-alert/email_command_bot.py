"""邮件指令机器人：读取 IMAP 未读邮件并解析运行时命令。"""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass, field
from email.header import decode_header
from email.utils import parseaddr
from typing import Any


def _guess_imap_server(sender_email: str) -> str:
    dom = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
    m = {
        "qq.com": "imap.qq.com",
        "foxmail.com": "imap.qq.com",
        "163.com": "imap.163.com",
        "126.com": "imap.126.com",
        "yeah.net": "imap.yeah.net",
        "gmail.com": "imap.gmail.com",
        "sina.com": "imap.sina.com",
        "yahoo.com": "imap.mail.yahoo.com",
        "outlook.com": "outlook.office365.com",
        "hotmail.com": "outlook.office365.com",
        "live.com": "outlook.office365.com",
    }
    return m.get(dom, "")


def _effective_email_command_settings(ec: dict[str, Any]) -> dict[str, Any]:
    """合并 config 与 mail_config（买卖提醒同一套账号）。"""
    out = dict(ec)
    if not bool(out.get("use_shared_mail_config", True)):
        return out
    try:
        from email_notify import load_mail_config
    except Exception:
        return out
    mail = load_mail_config()
    if not mail:
        return out
    if not str(out.get("imap_username") or "").strip():
        out["imap_username"] = str(mail.get("sender") or "").strip()
    if not str(out.get("imap_password") or "").strip():
        out["imap_password"] = str(mail.get("password") or "").strip()
    if not str(out.get("imap_server") or "").strip():
        ms = str(mail.get("imap_server") or "").strip()
        out["imap_server"] = ms or _guess_imap_server(str(out.get("imap_username") or ""))
    if mail.get("imap_port") is not None and not out.get("imap_port"):
        try:
            out["imap_port"] = int(mail.get("imap_port"))
        except (TypeError, ValueError):
            pass
    if str(mail.get("imap_folder") or "").strip() and not str(
        out.get("imap_folder") or ""
    ).strip():
        out["imap_folder"] = str(mail.get("imap_folder")).strip()
    ts = out.get("trusted_senders")
    if not isinstance(ts, list) or len([x for x in ts if str(x).strip()]) == 0:
        recv = mail.get("receivers") or []
        snd = str(mail.get("sender") or "").strip()
        merged = [str(x).strip().lower() for x in recv if str(x).strip()]
        if snd:
            merged.append(snd.lower())
        out["trusted_senders"] = list(dict.fromkeys(merged))
    return out


def _decode_header_text(raw: str | None) -> str:
    s = str(raw or "")
    out: list[str] = []
    for frag, enc in decode_header(s):
        if isinstance(frag, bytes):
            try:
                out.append(frag.decode(enc or "utf-8", errors="ignore"))
            except Exception:
                out.append(frag.decode("utf-8", errors="ignore"))
        else:
            out.append(str(frag))
    return "".join(out).strip()


def _extract_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        chunks: list[str] = []
        for part in msg.walk():
            ctype = str(part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                chs = part.get_content_charset() or "utf-8"
                chunks.append(payload.decode(chs, errors="ignore"))
        return "\n".join(chunks).strip()
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    chs = msg.get_content_charset() or "utf-8"
    return payload.decode(chs, errors="ignore").strip()


def _parse_runtime_commands(subject: str, body: str) -> list[str]:
    txt = (subject + "\n" + body).replace("\r", "\n")
    commands: list[str] = []
    sell_patterns = [
        r"([0-9]{6})\s*编号?\s*卖出",
        r"卖出\s*([0-9]{6})",
        r"([0-9]{6}).{0,12}卖出",
        r"\bsell\s*([0-9]{6})\b",
    ]
    for p in sell_patterns:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            code = m.group(1)
            cmd = f"sell {code}"
            if cmd not in commands:
                commands.append(cmd)
    # 买入：支持“600711编号买入”、“买入600711”
    # 以及“买入600711 300 10.25 / 600711编号买入 300股 10.25”等（自动转 hold）
    buy_patterns_with_pos = [
        r"([0-9]{6})\s*编号?\s*买入(?:\s*[:：]?\s*|\s+)([0-9]{1,9})\s*(?:股)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"买入\s*([0-9]{6})(?:\s*[:：]?\s*|\s+)([0-9]{1,9})\s*(?:股)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"\bbuy\s*([0-9]{6})\s+([0-9]{1,9})\s+([0-9]+(?:\.[0-9]+)?)\b",
    ]
    for p in buy_patterns_with_pos:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            code, shares, cost = m.group(1), m.group(2), m.group(3)
            cmd = f"hold {code} {int(shares)} {float(cost)}"
            if cmd not in commands:
                commands.append(cmd)

    buy_patterns_watch_only = [
        r"([0-9]{6})\s*编号?\s*买入",
        r"买入\s*([0-9]{6})",
        r"([0-9]{6}).{0,12}买入",
        r"\bbuy\s*([0-9]{6})\b",
    ]
    for p in buy_patterns_watch_only:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            code = m.group(1)
            cmd_full_prefix = f"hold {code} "
            if any(c.startswith(cmd_full_prefix) for c in commands):
                # 已有带仓位成本的 buy 命令，跳过弱命令
                continue
            cmd = f"hold {code}"
            if cmd not in commands:
                commands.append(cmd)
    return commands[:8]


def _parse_feedback_commands(subject: str, body: str) -> list[tuple[str, str]]:
    """
    解析邮件中的误报/真报指令，返回 (kind, code6)，kind 为 fp 或 tp。
    """
    txt = (subject + "\n" + body).replace("\r", "\n")
    out: list[tuple[str, str]] = []
    fp_patterns = [
        r"\bfp\s+([0-9]{6})\b",
        r"\bfalse\s*positive\s+([0-9]{6})\b",
        r"误报\s*[:：]?\s*([0-9]{6})\b",
        r"假阳性\s*[:：]?\s*([0-9]{6})\b",
    ]
    tp_patterns = [
        r"\btp\s+([0-9]{6})\b",
        r"\btrue\s*positive\s+([0-9]{6})\b",
        r"真报\s*[:：]?\s*([0-9]{6})\b",
    ]
    for p in fp_patterns:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            code = m.group(1)
            t = ("fp", code)
            if t not in out:
                out.append(t)
    for p in tp_patterns:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            code = m.group(1)
            t = ("tp", code)
            if t not in out:
                out.append(t)
    return out[:16]


@dataclass
class EmailBotPollResult:
    runtime_commands: list[str] = field(default_factory=list)
    feedback_commands: list[tuple[str, str]] = field(default_factory=list)


def fetch_email_bot_actions(cfg: dict[str, Any]) -> EmailBotPollResult:
    """拉取未读邮件：交易类 runtime 命令 + 预警反馈 fp/tp。"""
    ec0 = cfg.get("email_command_bot") or {}
    if not bool(ec0.get("enabled", False)):
        return EmailBotPollResult()
    ec = _effective_email_command_settings(ec0 if isinstance(ec0, dict) else {})
    host = str(ec.get("imap_server") or "").strip()
    user = str(ec.get("imap_username") or "").strip()
    password = str(ec.get("imap_password") or "").strip()
    folder = str(ec.get("imap_folder") or "INBOX").strip() or "INBOX"
    port = int(ec.get("imap_port") or 993)
    if not (host and user and password):
        return EmailBotPollResult()

    trusted = ec.get("trusted_senders") or []
    trusted_set = {str(x).strip().lower() for x in trusted if str(x).strip()}
    if not trusted_set:
        return EmailBotPollResult()
    mark_seen = bool(ec.get("mark_seen", True))
    cmds: list[str] = []
    fbs: list[tuple[str, str]] = []
    M: imaplib.IMAP4_SSL | None = None
    try:
        M = imaplib.IMAP4_SSL(host, port, timeout=20)
        M.login(user, password)
        typ, _ = M.select(folder, readonly=False)
        if typ != "OK":
            return EmailBotPollResult()
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return EmailBotPollResult()
        ids = data[0].split()[-30:]
        for mid in ids:
            typ, msg_data = M.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(raw)
            subj = _decode_header_text(msg.get("Subject"))
            sender = parseaddr(_decode_header_text(msg.get("From")))[1].strip().lower()
            body = _extract_text(msg)
            if trusted_set and sender not in trusted_set:
                if mark_seen:
                    M.store(mid, "+FLAGS", "\\Seen")
                continue
            cmds.extend(_parse_runtime_commands(subj, body))
            fbs.extend(_parse_feedback_commands(subj, body))
            if mark_seen:
                M.store(mid, "+FLAGS", "\\Seen")
    except Exception:
        return EmailBotPollResult()
    finally:
        try:
            if M is not None:
                M.close()
        except Exception:
            pass
        try:
            if M is not None:
                M.logout()
        except Exception:
            pass

    out_rt: list[str] = []
    seen_rt: set[str] = set()
    for c in cmds:
        if c not in seen_rt:
            seen_rt.add(c)
            out_rt.append(c)
    out_fb: list[tuple[str, str]] = []
    seen_fb: set[tuple[str, str]] = set()
    for t in fbs:
        if t not in seen_fb:
            seen_fb.add(t)
            out_fb.append(t)
    return EmailBotPollResult(
        runtime_commands=out_rt[:8],
        feedback_commands=out_fb,
    )


def fetch_runtime_commands_from_email(cfg: dict[str, Any]) -> list[str]:
    """兼容旧调用：仅返回交易类 runtime 命令。"""
    return fetch_email_bot_actions(cfg).runtime_commands
