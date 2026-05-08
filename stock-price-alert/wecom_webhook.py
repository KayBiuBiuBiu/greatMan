"""企业微信群机器人 Webhook（仅机器人密钥 URL，非应用消息）。

官方文档：https://developer.work.weixin.qq.com/document/path/91770
支持 msgtype: text、markdown（可用 <font color=\"warning\"> 等标签）。
"""

from __future__ import annotations

import logging
from typing import Any

import requests

_LOG = logging.getLogger(__name__)


def post_wecom_robot(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    timeout_sec: float = 15.0,
) -> tuple[bool, dict[str, Any] | None, int, str]:
    """
    执行 POST，返回 (是否 errcode==0, 解析后的 JSON 或 None, HTTP 状态码, 响应原文片段)。
    """
    url = (webhook_url or "").strip()
    if not url:
        return False, None, 0, ""
    try:
        r = requests.post(url, json=payload, timeout=timeout_sec)
        http = int(r.status_code)
        raw = (r.text or "")[:2000]
        try:
            data = r.json()
        except Exception:
            _LOG.warning("wecom webhook 响应非 JSON: http=%s body=%s", http, raw[:500])
            return False, None, http, raw
        if not isinstance(data, dict):
            return False, None, http, raw
        ec = int(data.get("errcode", -1))
        ok = ec == 0
        if not ok:
            _LOG.warning("wecom webhook err: %s", data)
        return ok, data, http, raw
    except Exception as exc:
        _LOG.warning("wecom webhook 请求失败: %s", exc)
        return False, None, 0, str(exc)


def _utf8_trim(s: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw = s.encode("utf-8")
    if len(raw) <= max_bytes:
        return s
    cut = max_bytes
    while cut > 0 and (raw[cut - 1] & 0xC0) == 0x80:
        cut -= 1
    return raw[:cut].decode("utf-8", errors="ignore") + "\n…(已截断)"


def send_wecom_robot_message(
    webhook_url: str,
    msgtype: str,
    subject: str,
    body: str,
    *,
    timeout_sec: float = 15.0,
) -> bool:
    """
    发送企业微信机器人消息。
    - text：content 总长不超过约 2048 字节（按 UTF-8 截断）。
    - markdown：content 不超过约 4096 字节；subject 作为二级标题拼在正文前。
    """
    url = (webhook_url or "").strip()
    if not url:
        return False
    mt = (msgtype or "markdown").strip().lower()
    if mt not in ("text", "markdown"):
        mt = "markdown"

    sub = (subject or "").strip() or "股价监控"
    bod = body or ""

    if mt == "text":
        text = f"{sub}\n{bod}".strip()
        text = _utf8_trim(text, 2040)
        payload: dict[str, Any] = {"msgtype": "text", "text": {"content": text}}
    else:
        # markdown：标题 + 正文；避免与 markdown 语法严重冲突时可自行在业务侧控制 body
        content = f"## {sub}\n\n{bod}".strip()
        content = _utf8_trim(content, 4080)
        payload = {"msgtype": "markdown", "markdown": {"content": content}}

    ok, data, http, _raw = post_wecom_robot(url, payload, timeout_sec=timeout_sec)
    if not ok and http and http != 200:
        _LOG.warning("wecom webhook HTTP %s: %s", http, _raw[:300])
    return ok


def build_wecom_payload(msgtype: str, subject: str, body: str) -> dict[str, Any]:
    """供测试与调试构造与正式发送一致的 payload（不发起网络请求）。"""
    mt = (msgtype or "markdown").strip().lower()
    if mt not in ("text", "markdown"):
        mt = "markdown"
    sub = (subject or "").strip() or "股价监控"
    bod = body or ""
    if mt == "text":
        text = f"{sub}\n{bod}".strip()
        text = _utf8_trim(text, 2040)
        return {"msgtype": "text", "text": {"content": text}}
    content = f"## {sub}\n\n{bod}".strip()
    content = _utf8_trim(content, 4080)
    return {"msgtype": "markdown", "markdown": {"content": content}}
