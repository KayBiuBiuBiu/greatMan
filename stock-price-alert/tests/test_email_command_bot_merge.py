from __future__ import annotations

import email_command_bot as ecb


def test_guess_imap_qq() -> None:
    assert ecb._guess_imap_server("a@qq.com") == "imap.qq.com"
    assert ecb._guess_imap_server("a@163.com") == "imap.163.com"


def test_effective_settings_fills_from_shared(monkeypatch) -> None:
    def fake_load() -> dict:
        return {
            "sender": "bot@qq.com",
            "password": "secret",
            "receivers": ["me@qq.com"],
            "smtp_server": "smtp.qq.com",
            "smtp_port": 465,
        }

    import email_notify

    monkeypatch.setattr(email_notify, "load_mail_config", fake_load)
    ec = {
        "enabled": True,
        "use_shared_mail_config": True,
        "imap_server": "",
        "imap_username": "",
        "imap_password": "",
        "trusted_senders": [],
    }
    merged = ecb._effective_email_command_settings(ec)
    assert merged["imap_username"] == "bot@qq.com"
    assert merged["imap_password"] == "secret"
    assert merged["imap_server"] == "imap.qq.com"
    assert "me@qq.com" in merged["trusted_senders"]
    assert "bot@qq.com" in merged["trusted_senders"]
