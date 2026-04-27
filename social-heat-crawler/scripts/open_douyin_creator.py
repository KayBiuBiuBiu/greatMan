#!/usr/bin/env python3
"""用已保存的抖音登录态，打开发布/上传页，便于你**本地上传**视频或图文（不自动抓视频）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 常见入口：内容上传
DEFAULT_URL = "https://creator.douyin.com/creator-micro/content/upload"

from social_heat_crawler.config import get_settings
from social_heat_crawler.crawlers.base import new_browser_context, play_start


def main() -> int:
    s = get_settings()
    s.headless = False
    if not s.storage_douyin.exists():
        print("缺少 data/storage_state_douyin.json，请先: python scripts/save_login_state.py --platform douyin")
        return 1
    p = play_start()
    browser = None
    ctx = None
    try:
        browser, ctx = new_browser_context(p, s, s.storage_douyin)
        page = ctx.new_page()
        page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=90_000)
        print("已打开发布页。上传本地视频/图文后自行发布。关闭浏览器即结束。")
        input("按 Enter 关闭浏览器…")
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        p.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
