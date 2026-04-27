"""
小红书发布页自动化（浏览器自动化，不走逆向 API）。

说明：
- 站点经常改版，以下选择器采用多候选回退；
- 自动化发布有风控风险，请低频使用；
- 默认会自动点击“发布”，可在脚本参数里切换为手动模式。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings
from ..human import human_delay
from ..crawlers.base import new_browser_context, play_start

DEFAULT_CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"

TITLE_SELECTORS = [
    "input[placeholder*='标题']",
    "input[placeholder*='写标题']",
    "textarea[placeholder*='标题']",
]
CONTENT_SELECTORS = [
    "div[contenteditable='true'][data-placeholder*='正文']",
    "div[contenteditable='true'][placeholder*='正文']",
    "div[contenteditable='true']",
    "textarea[placeholder*='正文']",
]
UPLOAD_INPUT_SELECTORS = [
    "input[type='file'][accept*='image']",
    "input[type='file'][multiple]",
    "input[type='file']",
]
PUBLISH_BUTTON_SELECTORS = [
    "button:has-text('发布笔记')",
    "button:has-text('立即发布')",
    "button:has-text('发布')",
]


def _try_locator(page: Any, selectors: list[str]) -> Any | None:
    """返回第一个 count>0 的 locator.first。"""
    for css in selectors:
        try:
            loc = page.locator(css)
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


def _fill_title(page: Any, title: str) -> None:
    loc = _try_locator(page, TITLE_SELECTORS)
    if loc is None:
        print("[publish][warn] 未找到标题输入框，请手动填写标题。")
        return
    try:
        loc.click(timeout=5000)
        loc.fill("")
        loc.type(title[:20], delay=35)
    except Exception as e:
        print(f"[publish][warn] 自动填写标题失败：{e}")


def _fill_content(page: Any, content: str) -> None:
    loc = _try_locator(page, CONTENT_SELECTORS)
    if loc is None:
        print("[publish][warn] 未找到正文输入框，请手动填写正文。")
        return
    try:
        loc.click(timeout=5000)
        # contenteditable 与 textarea 的清空方式不同，这里统一 Ctrl+A + Backspace
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
        loc.type(content[:1000], delay=25)
    except Exception as e:
        print(f"[publish][warn] 自动填写正文失败：{e}")


def _upload_images(page: Any, image_paths: list[Path]) -> None:
    if not image_paths:
        print("[publish] 未提供本地图片，跳过自动上传。")
        return
    files = [str(p) for p in image_paths if p.exists() and p.is_file()]
    if not files:
        print("[publish][warn] 图片路径无效，跳过自动上传。")
        return
    loc = _try_locator(page, UPLOAD_INPUT_SELECTORS)
    if loc is None:
        print("[publish][warn] 未找到上传 input[type=file]，请手动上传。")
        return
    try:
        loc.set_input_files(files)
        print(f"[publish] 已尝试自动上传 {len(files)} 张图片。")
    except Exception as e:
        print(f"[publish][warn] 自动上传失败：{e}")


def _click_publish(page: Any) -> bool:
    loc = _try_locator(page, PUBLISH_BUTTON_SELECTORS)
    if loc is None:
        print("[publish][warn] 未找到发布按钮，请手动点击发布。")
        return False
    try:
        loc.click(timeout=8000)
        return True
    except Exception as e:
        print(f"[publish][warn] 点击发布失败：{e}")
        return False


def publish_note(
    settings: Settings,
    *,
    title: str,
    content: str,
    image_paths: list[Path] | None = None,
    auto_submit: bool = True,
    wait_after_submit_sec: int = 8,
) -> bool:
    """
    自动打开发布页 -> 填标题正文 -> 上传图片 -> (可选)自动点击发布。
    """
    image_paths = image_paths or []
    p = play_start()
    # 发布页/创作者中心按桌面版布局，勿用手机模拟
    browser, ctx = new_browser_context(p, settings, settings.storage_xhs, emulate_mobile=False)
    page = ctx.new_page()
    ok = False
    try:
        page.goto(DEFAULT_CREATOR_URL, wait_until="domcontentloaded", timeout=120_000)
        human_delay(settings.delay_min, settings.delay_max)

        _fill_title(page, title or "")
        human_delay(0.6, 1.5)
        _fill_content(page, content or "")
        human_delay(0.6, 1.6)
        _upload_images(page, image_paths)
        human_delay(2.0, 4.0)

        if auto_submit:
            print("[publish] 准备自动点击发布按钮…")
            ok = _click_publish(page)
            if ok:
                print("[publish] 已触发发布点击，请检查页面提示确认是否成功。")
                page.wait_for_timeout(wait_after_submit_sec * 1000)
            else:
                print("[publish] 自动发布未成功，请手动确认。")
        else:
            print("发布按钮已就绪，请人工确认。")
            if not settings.headless:
                input("确认后回车关闭浏览器…")
            ok = True
    except Exception as e:
        print("打开或发布失败，请检查登录态/页面改版：", e)
        ok = False
    finally:
        try:
            ctx.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass
    return ok
