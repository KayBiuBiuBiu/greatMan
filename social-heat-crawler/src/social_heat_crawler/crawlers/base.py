from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings

_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 降低通知、首次运行气泡；无法 100% 消掉系统级「调起本机 App / 其他应用」条，可手动点「屏蔽」
CHROMIUM_LAUNCH_ARGS: list[str] = [
    "--disable-notifications",
    "--no-default-browser-check",
    "--no-first-run",
]


def play_start() -> Any:
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


def _device_dict(p: Any, preferred: str) -> dict[str, Any]:
    """
    取 Playwright 内置机型的 viewport / UA / is_mobile / has_touch 等，避免被站点当成桌面而拦截。
    """
    d = p.devices
    for key in (preferred, "iPhone 12", "iPhone 13", "iPhone 14", "Pixel 5"):
        if key in d:
            return dict(d[key])
    # 极端兜底：近似移动 Safari
    return {
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3.0,
        "is_mobile": True,
        "has_touch": True,
    }


def new_browser_context(
    p: Any,
    settings: Settings,
    storage: Path | None,
    *,
    emulate_mobile: bool | None = None,
) -> tuple[Any, Any]:
    """
    launch + new_context，带已保存的 storage_state。

    - 爬取/日常浏览小红书：默认 emulate_mobile=True，与「手机端网页」行为一致，减少仅手机可查看。
    - 创作者中心发笔记：在调用处传 emulate_mobile=False，使用桌面视口与 UA。
    """
    browser = p.chromium.launch(
        headless=settings.headless,
        args=CHROMIUM_LAUNCH_ARGS,
    )
    st = str(storage) if storage and storage.exists() else None
    use_mobile = (
        bool(settings.xhs_emulate_mobile) if emulate_mobile is None else bool(emulate_mobile)
    )

    kwargs: dict[str, Any] = {"locale": "zh-CN"}
    if st:
        kwargs["storage_state"] = st

    if use_mobile:
        dev = _device_dict(p, (settings.xhs_device or "iPhone 12").strip())
        ctx = browser.new_context(**{**dev, **kwargs})
    else:
        ctx = browser.new_context(
            **kwargs,
            viewport={"width": 1280, "height": 900},
            user_agent=_DESKTOP_UA,
        )
    return browser, ctx
