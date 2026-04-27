#!/usr/bin/env python3
"""手动登录后保存平台登录态（目前实现 xiaohongshu）。"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Frame,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_heat_crawler.crawlers.base import CHROMIUM_LAUNCH_ARGS, play_start

# 与 crawlers 分离：保存登录时强制用明确的移动 Safari UA + 小视口，避免被重定向到「下载 App」
MOBILE_USER_AGENT: str = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 "
    "Safari/604.1"
)
MOBILE_VIEWPORT: dict[str, int] = {"width": 375, "height": 667}
LOGIN_URL = "https://www.xiaohongshu.com/login"
HOME_URL = "https://www.xiaohongshu.com"
STATE_RELPATH = "data/storage_state_xhs.json"

# 主文档 + iframe
_LOGIN_LOCATORS: list[str] = [
    'button:has-text("登录")',
    'a:has-text("登录")',
    "div.login-btn",
    'a[href="/login"]',
    'a[href*="/login"]',
    '[class*="login-btn"]',
    '[class*="LoginBtn"]',
    'div:has-text("登录")',
]
_PROFILE_FALLBACK_LOCATORS: list[str] = [
    '[class*="avatar"]',
    '[class*="user-avatar"]',
    'a[href*="/user/profile"]',
    "text=我的",
    '[aria-label="我的"]',
    '[class*="profile"]',
]

# 下载 App 拦截页上的可能入口
_BYPASS_TEXT_CANDIDATES: list[str] = [
    "使用电脑版",
    "在电脑打开",
    "在浏览器中打开",
    "继续访问网页版",
    "在网页继续",
    "继续访问",
    "暂不下载",
    "在浏览器中继续",
    "在浏览器中访问",
    "在网页版中打开",
]


def _is_xhs_logged_in(context: BrowserContext) -> bool:
    try:
        cookies = context.cookies("https://www.xiaohongshu.com")
    except Exception:  # noqa: BLE001
        return False
    if not cookies:
        return False
    names = {c.get("name", "") for c in cookies}
    return ("web_session" in names) or ("web_session_2" in names)


def _click_if_visible(parent: Page | Frame, sel: str, timeout_ms: int = 4_000) -> bool:
    try:
        loc = parent.locator(sel)
        if loc.count() == 0:
            return False
        first = loc.first
        if not first.is_visible():
            return False
        first.click(timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def _iter_frames_hierarchy(page: Page) -> list[Frame | Page]:
    out: list[Frame | Page] = [page]
    seen: set[Frame] = set()
    for fr in list(page.frames):
        if fr not in seen:
            seen.add(fr)
            out.append(fr)
    return out


def _try_open_login_in_scope(parent: Page | Frame) -> bool:
    for sel in _LOGIN_LOCATORS:
        if _click_if_visible(parent, sel):
            return True
    try:
        btn = parent.get_by_role("button", name="登录")
        if btn.count() and btn.first.is_visible():
            btn.first.click(timeout=4_000)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        t = parent.get_by_text("登录", exact=True)
        if t.count() and t.first.is_visible():
            t.first.click(timeout=4_000)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _try_open_login_on_page_and_frames(page: Page) -> bool:
    for target in _iter_frames_hierarchy(page):
        if _try_open_login_in_scope(target):
            return True
    return False


def _try_open_profile_to_trigger_login(page: Page) -> bool:
    for target in _iter_frames_hierarchy(page):
        for sel in _PROFILE_FALLBACK_LOCATORS:
            try:
                if _click_if_visible(target, sel, timeout_ms=3_000):
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _page_text_snippet(page: Page) -> str:
    try:
        b = page.locator("body")
        if b.count() == 0:
            return ""
        return (b.first.inner_text(timeout=8_000) or "")[:10000]
    except Exception:  # noqa: BLE001
        return ""


def _page_looks_like_download_app_gate(page: Page) -> bool:
    """出现「拉 App / 不给你网页版」的落地页，常见含「下载 App」等语。"""
    t = _page_text_snippet(page)
    u = (page.url or "").lower()
    if not t and not u:
        return False
    low = t.lower()
    if "下载" in t and "app" in low:
        return True
    if "下载" in t and "小红书" in t and ("立即" in t or "体验" in t or "手机" in t):
        return True
    if "在app内打开" in t or "打开app" in low or "去app" in low:
        return True
    return "download" in u and "xiaohongshu" in u  # 保守


def _try_bypass_app_download_interstitial(page: Page) -> bool:
    """
    若落在新用户「下载 App」等页，尝试点「使用电脑版」「继续访问网页版」等。
    在 Page 及所有子 frame 上尝试；匹配不到则 False。
    """
    for target in _iter_frames_hierarchy(page):
        for label in _BYPASS_TEXT_CANDIDATES:
            for exact in (True, False):
                try:
                    n2 = target.get_by_text(label, exact=exact)
                    if n2.count() and n2.first.is_visible():
                        n2.first.click(timeout=3_000)
                        return True
                except Exception:  # noqa: BLE001
                    continue
        for sel in (
            'a:has-text("电脑")',
            'a:has-text("网页")',
            'a:has-text("浏览器")',
        ):
            if _click_if_visible(target, sel, 2_500):
                return True
        try:
            lnk = target.get_by_role("link", name=re.compile("电脑|网页|浏览器|继续", re.I))
            if lnk.count() and lnk.first.is_visible():
                lnk.first.click(timeout=3_000)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _wait_steady(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=60_000)
    except PlaywrightTimeout:
        try:
            page.wait_for_load_state("load", timeout=20_000)
        except Exception:  # noqa: BLE001
            time.sleep(2.0)
    time.sleep(0.6)


def _apply_download_gate_bypass_routine(page: Page) -> None:
    """多轮：检测下载页则点「网页版」等，再回登录或等待跳转。"""
    for _ in range(3):
        if not _page_looks_like_download_app_gate(page):
            break
        print("[xhs] 检测到「下载 App」类引导页，尝试点「使用电脑版 / 继续访问网页版」…")
        if _try_bypass_app_download_interstitial(page):
            time.sleep(1.5)
            _wait_steady(page)
            continue
        time.sleep(0.5)
        if not _page_looks_like_download_app_gate(page):
            break
    if _page_looks_like_download_app_gate(page):
        print(
            "[xhs] 未能自动点出网页版。请手点「使用电脑版/继续访问网页版」，"
            "或忽略本提示仍可在下方操作。"
        )


def _new_save_login_browser(
    pw: Playwright, headless: bool = False
) -> tuple[Browser, BrowserContext]:
    """
    专用 new_context：固定移动 UA + 小视口 + 触摸/移动设备标记，与 crawlers 解耦、避免下载页。
    """
    browser = pw.chromium.launch(headless=headless, args=CHROMIUM_LAUNCH_ARGS)
    context = browser.new_context(
        user_agent=MOBILE_USER_AGENT,
        viewport=MOBILE_VIEWPORT,
        locale="zh-CN",
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2.0,
    )
    return browser, context


def _save_xhs_state() -> int:
    state_path = ROOT / STATE_RELPATH
    state_path.parent.mkdir(parents=True, exist_ok=True)

    pw: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    try:
        # 显式有头
        pw = play_start()
        browser, context = _new_save_login_browser(pw, headless=False)
        if context is None:  # pragma: no cover
            print("无法创建浏览器。")
            return 1
        page = context.new_page()

        # 3) 直接开登录地址（与首页相比更易落在网页登录/扫码）
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120_000)
        _wait_steady(page)
        # 4) 若被强制到「下载 App」
        _apply_download_gate_bypass_routine(page)

        low_url = (page.url or "").lower()
        if "login" not in low_url and "passport" not in low_url and not _try_open_login_on_page_and_frames(
            page
        ):
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=90_000)
                _wait_steady(page)
                _apply_download_gate_bypass_routine(page)
            except Exception as e:  # noqa: BLE001
                print(f"[xhs] 再次打开 /login: {e}")

        low_url = (page.url or "").lower()
        if "login" not in low_url and "passport" not in low_url and "captcha" not in low_url:
            try:
                print("[xhs] 若仍未出现登录，尝试从首页点「登录」…")
                page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90_000)
                _wait_steady(page)
                _apply_download_gate_bypass_routine(page)
                if not _try_open_login_on_page_and_frames(page):
                    _ = _try_open_profile_to_trigger_login(page)
            except Exception as e:  # noqa: BLE001
                print(f"[xhs] 打开首页: {e}")
        time.sleep(0.5)
        if not _try_open_login_on_page_and_frames(page):
            _ = _try_open_profile_to_trigger_login(page)

        if _page_looks_like_download_app_gate(page):
            print("手动点击页面上的登录/网页版入口，完成登录后按下面提示。")
        time.sleep(1.0)
        uu = (page.url or "")
        if not any(
            k in uu.lower() for k in ("login", "passport", "captcha", "h5", "h5s", "qrcode")
        ):
            print("手动点击页面上的登录按钮后按 Enter")
        else:
            print("若已看到登录/扫码，请完成登录，然后按 Enter")

        print("请在弹出的浏览器中扫码或验证码登录，登录成功后按 Enter 键继续")
        input()

        if not _is_xhs_logged_in(context):
            print("未检测到有效登录态（可能尚未完成登录）。请重新运行并在登录成功后再按 Enter。")
            return 2

        context.storage_state(path=str(state_path))
        print("登录态已保存到", STATE_RELPATH)
        return 0
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"保存登录态失败：{e}")
        return 1
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:  # noqa: BLE001
            pass


def _is_douyin_logged_in(context: BrowserContext) -> bool:
    """有常见会话 cookie 或 cookie 条数足够多即认为已登录（粗检）。"""
    try:
        cookies = context.cookies("https://www.douyin.com")
    except Exception:  # noqa: BLE001
        return False
    if not cookies:
        return False
    names = {c.get("name", "") for c in cookies}
    if names & {"ttwid", "sessionid", "sid_tt", "passport_csrf_token", "msToken"}:
        return True
    return len(cookies) >= 5


def _save_douyin_state() -> int:
    """抖音：与 run_crawl 同构（config + new_browser_context 桌面/当前设置），有头打开后手动扫码。"""
    from social_heat_crawler.config import get_settings
    from social_heat_crawler.crawlers.base import new_browser_context

    state_path = ROOT / "data" / "storage_state_douyin.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    s.headless = False
    pw: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    try:
        pw = play_start()
        browser, context = new_browser_context(pw, s, None)
        page = context.new_page()
        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=120_000)
        try:
            page.wait_for_load_state("load", timeout=30_000)
        except Exception:  # noqa: BLE001
            time.sleep(2.0)
        time.sleep(1.0)
        print(
            "请在本窗口中完成登录（通常点右上角「登录」并扫码/验证）。\n"
            "登录完成后回到终端按 Enter 以保存到 data/storage_state_douyin.json"
        )
        input()
        if not _is_douyin_logged_in(context):
            print("未检测到明显登录态。若已登录可忽略本提示重试，否则请成功登录后再按 Enter。")
            return 2
        context.storage_state(path=str(state_path))
        print("登录态已保存到 data/storage_state_douyin.json")
        return 0
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"保存失败：{e}")
        return 1
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="保存平台登录态（xiaohongshu / douyin）"
    )
    parser.add_argument(
        "--platform",
        choices=("xiaohongshu", "douyin"),
        default="douyin",
        help="xiaohongshu=小红书；douyin=抖音（默认）",
    )
    args = parser.parse_args()

    if args.platform == "xiaohongshu":
        code = _save_xhs_state()
    else:
        code = _save_douyin_state()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
