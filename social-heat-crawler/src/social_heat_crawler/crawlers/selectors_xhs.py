"""
小红书（详情页/搜索）CSS 选择器与解析辅助。

说明：
- 站点常改版，本文件为「多候选、按序尝试」；请用浏览器 DevTools 对真实 DOM 增删行。
- 任一字段时间失败不会抛异常，只打警告，便于其它字段继续解析。
- 环境变量 XHS_DEBUG=1 时，当某字段所有候选均失败，会将当前页 HTML 落盘到 config.debug_html_dir（默认 data/debug/）。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 搜索列表页：笔记链接（href 中需含 /explore/ 或 discovery）
# ---------------------------------------------------------------------------
NOTE_LINK_SELECTORS: list[str] = [
    'a[href*="/explore/"]',
    'a[href*="/discovery/item/"]',
    'div[class*="note"] a[href*="/explore/"]',
    'section a[href*="/explore/"]',
    'div[class*="feed"] a[href*="/explore/"]',
]

# 与旧版兼容：单 CSS 多匹配（逗号在 Playwright 中可用）
NOTE_LINK: str = ', '.join(NOTE_LINK_SELECTORS[:2])

NOTE_CARD_CANDIDATES: list[str] = [
    "section.note-item",
    "div.search-note-item",
    "div.note-item",
    "div.feed-card",
    'div[class*="NoteCard"]',
    'div[class*="note"]',
]

# ---------------------------------------------------------------------------
# 详情页：标题（文本节点）
# ---------------------------------------------------------------------------
DETAIL_TITLE_SELECTORS: list[str] = [
    "h1#detail-title",
    "h1[class*='title']",
    "div[class*='title'] h1",
    "#noteContainer h1",
    ".note-content h1",
    "main h1",
    "article h1",
    "[class*='note-detail'] h1",
    "[class*='NoteDetail'] h1",
    "[class*='feed'] [class*='title']",
]

# ---------------------------------------------------------------------------
# 详情页：正文/描述
# ---------------------------------------------------------------------------
DETAIL_DESC_SELECTORS: list[str] = [
    "#detail-desc",
    "div#detail-desc",
    "[class*='desc'][class*='detail']",
    "div.note-text",
    ".note-content",
    "main [class*='desc']",
    "[id*='content'][class*='desc']",
    "article [class*='text']",
    "[class*='note-detail'] [class*='text']",
]

# ---------------------------------------------------------------------------
# 详情页：点赞区 —— 常为小号数字或「1.2万」，用 inner_text
# ---------------------------------------------------------------------------
LIKE_TEXT_SELECTORS: list[str] = [
    "span[class*='like']",
    "div[class*='like'] span",
    "button[aria-label*='赞'] + span",
    "[class*='like-icon'] + span",
    "[class*='interaction'] [class*='like']",
    "[class*='engagement'] [class*='like']",
    "[class*='footer'] [class*='like'] span",
]

# ---------------------------------------------------------------------------
# 评论数
# ---------------------------------------------------------------------------
COMMENT_TEXT_SELECTORS: list[str] = [
    "span[class*='comment']",
    "div[class*='comment'] span",
    "button[aria-label*='评论'] + span",
    "[class*='comment-icon'] + span",
    "[class*='interaction'] [class*='comment']",
    "[class*='engagement'] [class*='comment']",
    "button[aria-label='评论'] ~ span",
    "a[href*='comment'] span",
]

# ---------------------------------------------------------------------------
# 收藏数
# ---------------------------------------------------------------------------
COLLECT_TEXT_SELECTORS: list[str] = [
    "span[class*='collect']",
    "span[class*='fav']",
    "div[class*='collect'] span",
    "[class*='interaction'] [class*='collect']",
    "[class*='star'] + span",
    "[class*='engagement'] [class*='collect']",
    "button[aria-label*='收藏'] + span",
    "[class*='fav'] + span",
]

# ---------------------------------------------------------------------------
# 详情页：图片 <img>（按序尝试，直到凑够条数；排除头像）
# ---------------------------------------------------------------------------
IMG_SELECTORS: list[str] = [
    "div[class*='note'] img",
    "section[class*='content'] img",
    ".note-content img",
    "picture img",
    "article img",
    "div[class*='swiper'] img",
    "div[class*='slide'] img",
    "div[class*='slider'] img",
    "div[class*='carousel'] img",
    "div[class*='scroll'] img",
    "div[class*='media'] img",
    "img[src*='sns-webpic']",
    "img[src*='xhscdn']",
    "img[src*='ci.xiaohongshu.com']",
    "main img",
]

def _xhs_debug_on() -> bool:
    return os.environ.get("XHS_DEBUG", "").strip() in ("1", "true", "True", "yes", "on")


def _debug_html_dir() -> Path:
    """从全局配置取调试目录，避免在仅导入本模块时写死路径。"""
    try:
        from ..config import get_settings

        p = get_settings().debug_html_dir
        if isinstance(p, Path):
            return p
        return Path(str(p))
    except Exception:
        return Path("data/debug")


def _safe_file_stem(url: str, field_name: str) -> str:
    u = re.sub(r"[^\w\u4e00-\u9fff.]+", "_", (url or "page")[:80])
    t = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{u}_{field_name}_{t}"


def save_debug_page_html(
    page: Any,
    field_name: str,
    page_url: str = "",
    reason: str = "all_selectors_failed",
) -> Path | None:
    """
    将当前 page 的 HTML 存到 data/debug/（或 config.debug_html_dir）。

    调用场景：XHS_DEBUG=1 且某字段所有候选选择器均未命中时。
    """
    if not _xhs_debug_on():
        return None
    d = _debug_html_dir()
    d.mkdir(parents=True, exist_ok=True)
    stem = _safe_file_stem(page_url or "unknown", f"{field_name}_{reason}")
    path = d / f"{stem}.html"
    try:
        content = page.content()
        path.write_text(content, encoding="utf-8")
        print(f"[xhs][debug] 已保存调试 HTML: {path}")
    except Exception as e:  # noqa: BLE001
        print(f"[xhs][debug] 无法写入调试 HTML: {e}")
        return None
    return path


def find_with_fallback(
    page: Any,
    selectors: list[str],
    *,
    attribute: str | None = None,
    default: Any = None,
    field_name: str = "field",
    page_url: str = "",
    on_all_failed: Callable[[], None] | None = None,
) -> Any:
    """
    按顺序用 Playwright 选择器取**第一个**有效结果。

    - attribute=None 时，取 `inner_text().strip()`；空串视为未命中，继续下一候选。
    - attribute 非空时，取 `get_attribute(attribute)`；None 与空串继续尝试下一候选。

    全部失败时：
    - 打印一条中文警告（含 field_name 与 url 前 80 字）；
    - 若 XHS_DEBUG=1，将当前页 HTML 写入 data/debug/；
    - 可传入 on_all_failed 作额外处理；
    - 返回 default（通常为 None），**不**向外抛错。

    :param page: Playwright 的 Page 实例
    :param selectors: 不含逗号多路时的单条 CSS 列表，顺序即优先级
    :param attribute: 例如 'src'、'href'、'data-count'
    :param default: 全部失败时的返回值
    :param field_name: 仅用于日志与调试文件名
    :param page_url: 仅用于日志
    :param on_all_failed: 全部失败时回调
    """
    for css in selectors:
        css = (css or "").strip()
        if not css:
            continue
        try:
            loc = page.locator(css)
            cnt = loc.count()
            if cnt == 0:
                continue
            first = loc.first
            if attribute is not None:
                val = first.get_attribute(attribute)
                if val is not None and str(val).strip() != "":
                    return str(val)  # type: ignore[return-value]
            else:
                try:
                    raw = first.inner_text(timeout=4_000)
                except Exception:
                    continue
                if raw and raw.strip():
                    return raw.strip()  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            continue

    u = (page_url or "")[:80]
    print(
        f"[xhs][warn] 选择器全部未命中：字段「{field_name}」；"
        f"已尝试 {len(selectors)} 个候选。url={u}"
    )
    if on_all_failed is not None:
        try:
            on_all_failed()
        except Exception as e:  # noqa: BLE001
            print(f"[xhs][warn] on_all_failed 回调异常: {e}")
    if _xhs_debug_on():
        try:
            save_debug_page_html(page, field_name, page_url=page_url, reason="find_with_fallback")
        except Exception as e:  # noqa: BLE001
            print(f"[xhs][warn] 调试 HTML 未写出: {e}")
    return default


def parse_count_text(s: str) -> int:
    """
    将「123」「1.2万」等转为 int；与 xhs_crawler._parse_count 逻辑保持一致，避免循环导入。
    """
    s = (s or "").strip()
    if not s:
        return 0
    m = re.search(r"(\d+\.?\d*)\s*万", s)
    if m:
        return int(float(m.group(1)) * 10000)
    m2 = re.search(r"(\d+)", s.replace(",", ""))
    return int(m2.group(1)) if m2 else 0


def find_interaction_count_from_texts(
    page: Any,
    selectors: list[str],
    *,
    field_name: str,
    page_url: str = "",
) -> int | None:
    """
    对赞/评/藏：从候选节点取 inner_text，再 parse_count_text。
    若无法从任何节点解析出数字，打印警告；XHS_DEBUG=1 时写 HTML；返回 None。
    """
    for css in selectors:
        css = (css or "").strip()
        if not css:
            continue
        try:
            loc = page.locator(css)
            if loc.count() == 0:
                continue
            raw = loc.first.inner_text(timeout=3_000)
            if not raw or not re.search(r"\d", raw):
                continue
            n = parse_count_text(raw)
            return n
        except Exception:  # noqa: BLE001
            continue

    u = (page_url or "")[:80]
    print(
        f"[xhs][warn] 互动数选择器全部未命中：「{field_name}」；"
        f"已尝试 {len(selectors)} 个候选。url={u}"
    )
    if _xhs_debug_on():
        try:
            save_debug_page_html(
                page, field_name, page_url=page_url, reason="interaction_count"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[xhs][warn] 调试 HTML 未写出: {e}")
    return None


def collect_image_urls(
    page: Any,
    *,
    selectors: list[str] | None = None,
    max_count: int = 12,
    page_url: str = "",
    field_name: str = "images",
) -> list[str]:
    """
    按顺序尝试多组 img 选择器，收集 src / data-src（http 开头），去重、过滤头像关键词。
    若最终仍为空且 XHS_DEBUG=1，可写一份调试 HTML（仅当所有选择器下 img 数为 0）。
    """
    sel_list = selectors if selectors is not None else IMG_SELECTORS
    got: list[str] = []
    seen: set[str] = set()
    for css in sel_list:
        if len(got) >= max_count:
            break
        css = (css or "").strip()
        if not css:
            continue
        try:
            loc = page.locator(css)
            n = min(loc.count(), 40)
            for i in range(n):
                if len(got) >= max_count:
                    break
                try:
                    img = loc.nth(i)
                    src = (
                        img.get_attribute("src")
                        or img.get_attribute("data-src")
                        or img.get_attribute("data-original")
                        or img.get_attribute("data-lazy")
                        or img.get_attribute("data-ks-lazyload")
                    )
                    if not src or not src.startswith("http"):
                        continue
                    low = src.lower()
                    if any(
                        x in low
                        for x in ("avatar", "icon", "emoji", "data:image")
                    ):
                        continue
                    if src not in seen:
                        seen.add(src)
                        got.append(src)
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            continue

    if not got:
        print(
            f"[xhs][warn] 未收集到图片 URL：已尝试 {len(sel_list)} 组选择器。url={(page_url or '')[:80]}"
        )
        if _xhs_debug_on():
            try:
                save_debug_page_html(
                    page, field_name, page_url=page_url, reason="no_images"
                )
            except Exception as e:  # noqa: BLE001
                print(f"[xhs][warn] 调试 HTML 未写出: {e}")
    return got[:max_count]


# 兼容旧代码：单字符串（不宜含多路逗号，仅供老 import）
DETAIL_TITLE = DETAIL_TITLE_SELECTORS[0]
DETAIL_DESC = DETAIL_DESC_SELECTORS[0]
