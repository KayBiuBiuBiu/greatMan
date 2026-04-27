"""打开发布页、仅自动填标题，不上传媒体；按 Enter 后关浏览器。"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..human import human_delay
from ..crawlers.base import new_browser_context, play_start


def open_douyin_upload_and_fill_title(settings: Settings, title: str) -> bool:
    """
    用 storage_state_douyin 打开发布页，尽量填入标题，然后阻塞等待人工上传/发布。
    """
    if not settings.storage_douyin.exists():
        print("[publish][dy] 缺少 data/storage_state_douyin.json，请先 save_login_state --platform douyin")
        return False
    s = settings
    s.headless = False
    p = play_start()
    browser = None
    ctx = None
    try:
        browser, ctx = new_browser_context(
            p, s, s.storage_douyin, emulate_mobile=False
        )
        page = ctx.new_page()
        page.goto(
            str(s.douyin_creator_upload_url),
            wait_until="domcontentloaded",
            timeout=int(s.douyin_goto_timeout_ms),
        )
        human_delay(
            float(s.douyin_publish_delay_min),
            float(s.douyin_publish_delay_max),
        )
        if not _try_fill_title(page, s, (title or "").strip() or "无标题"):
            print(
                "[publish][dy] 未自动匹配到标题框，请手动填写。可改 .env 中 SHT_DOUYIN_TITLE_INPUT_SELECTORS。"
            )
        print(
            "[publish][dy] 已打开发布页。请在本窗口上传视频、检查文案后发布；"
            "完成后切回终端按 Enter 关闭浏览器。"
        )
        input()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[publish][dy] 失败: {e}")
        return False
    finally:
        try:
            if ctx is not None:
                ctx.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass


def _parse_selector_list(raw: str) -> list[str]:
    parts: list[str] = []
    for part in (raw or "").split(","):
        t = part.strip()
        if t:
            parts.append(t)
    return parts


def _try_fill_title(page: Any, settings: Settings, title: str) -> bool:
    sels = _parse_selector_list(settings.douyin_title_input_selectors)
    if not sels:
        sels = ['input[placeholder*="标题"]', "textarea[placeholder*='标题']"]
    for css in sels:
        try:
            loc = page.locator(css)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=5_000)
                loc.first.fill(title[:500])
                return True
        except Exception:  # noqa: BLE001
            continue
    return False
