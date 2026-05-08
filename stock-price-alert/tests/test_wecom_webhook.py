"""企业微信机器人 Webhook 与 email_notify 投递分发。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from email_notify import send_email_alert
from wecom_webhook import send_wecom_robot_message


def test_send_wecom_robot_markdown_ok() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"errcode":0,"errmsg":"ok"}'
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    with patch("wecom_webhook.requests.post", return_value=mock_resp) as p:
        ok = send_wecom_robot_message(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            "markdown",
            "标题",
            "正文<font color=\"warning\">高亮</font>",
        )
    assert ok is True
    p.assert_called_once()
    _args, kwargs = p.call_args
    payload = kwargs.get("json")
    assert isinstance(payload, dict)
    assert payload["msgtype"] == "markdown"
    assert "## 标题" in payload["markdown"]["content"]


def test_send_email_alert_wecom_only() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"errcode":0,"errmsg":"ok"}'
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    cfg = {
        "notifications": {
            "remote_channel": "wecom",
            "wecom_webhook": {
                "enabled": True,
                "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x",
                "msgtype": "text",
            },
        }
    }
    with patch("wecom_webhook.requests.post", return_value=mock_resp):
        with patch("email_notify._load_mail_cfg", return_value=None):
            ok = send_email_alert(
                "子",
                "内",
                append_disclaimer=False,
                app_cfg=cfg,
            )
    assert ok is True


def test_send_email_alert_none() -> None:
    cfg = {"notifications": {"remote_channel": "none"}}
    ok = send_email_alert("a", "b", append_disclaimer=False, app_cfg=cfg)
    assert ok is False
