from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..human import human_delay
from ..scoring import heat_score, top_n
from ..storage import download_file, safe_slug
from . import selectors_douyin as dsel
from .base import new_browser_context, play_start
from .selectors_xhs import (
    collect_image_urls,
    find_interaction_count_from_texts,
    find_with_fallback,
    parse_count_text,
)

_BODY_NUM_PATTERNS: dict[str, tuple[str, ...]] = {
    "likes": (r"获赞[：\s]*(\d+\.?\d*万|\d+)", r"赞[：\s]*(\d+\.?\d*万|\d+)"),
    "comments": (r"评论[：\s]*(\d+\.?\d*万|\d+)", r"(\d+\.?\d*万|\d+)\s*条评论"),
    "shares": (r"分享[：\s]*(\d+\.?\d*万|\d+)",),
    "collects": (r"收藏[：\s]*(\d+\.?\d*万|\d+)", r"(\d+\.?\d*万|\d+)\s*人收藏"),
}


def _parse_count(s: str) -> int:
    return parse_count_text(s)


def _norm_douyin_video_url(h: str) -> str | None:
    if not h or "/video/" not in h:
        return None
    h = h.strip()
    if h.startswith("//"):
        h = "https:" + h
    if h.startswith("/"):
        h = "https://www.douyin.com" + h
    h = h.split("?")[0]
    if "douyin.com" in h and "/video/" in h:
        return h
    return None


def search_url(keyword: str) -> str:
    q = urllib.parse.quote(keyword, safe="")
    return f"https://www.douyin.com/search/{q}"


def _scroll_page(page: Any, times: int, dmin: float, dmax: float) -> None:
    for _ in range(times):
        page.mouse.wheel(0, 1200)
        human_delay(dmin, dmax)


def _collect_video_hrefs(page: Any, limit: int) -> list[str]:
    hrefs: list[str] = []
    for sel_css in dsel.VIDEO_LINK_SELECTORS:
        try:
            group = page.locator(sel_css)
            n = min(group.count(), 80)
            for i in range(n):
                a = group.nth(i)
                h = a.get_attribute("href")
                u = _norm_douyin_video_url(h or "")
                if u and u not in hrefs:
                    hrefs.append(u)
        except Exception:  # noqa: BLE001
            continue
    return hrefs[:limit]


def _safe_page_title(page: Any) -> str:
    try:
        t = page.title()
        return (t or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _meta_content(page: Any, css: str) -> str:
    try:
        loc = page.locator(css)
        if loc.count() == 0:
            return ""
        c = loc.first.get_attribute("content")
        return (c or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _extract_play_url_from_html(html: str) -> str | None:
    """从详情页 HTML 中尽量取 mp4 直链（站点多变，不保证成功）。"""
    for pat in (
        r'"(https://[^"\\]+?\.mp4[^"\\]*)"',
        r"(https://aweme\.snssdk\.com/[^\"']+\.mp4[^\"']*)",
        r'"play_addr"[^}]{0,2000}?"url"\s*:\s*"(https:[^"]+)"',
    ):
        m = re.search(pat, html, re.DOTALL)
        if m and m.lastindex:
            u = m.group(1)
            if u.startswith("http") and "mp4" in u.lower():
                return u.split("\\u0026")[0]  # 少数字符串被转义
    return None


def _scrape_video_page(page: Any, url: str) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    out: dict[str, Any] = {
        "url": url,
        "video_url": url,
        "title": None,
        "body": None,
        "likes": 0,
        "comments": 0,
        "collects": 0,
        "shares": 0,
        "play_url": None,
        "video_download_url": None,
        "image_urls": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "platform": "douyin",
    }
    try:
        to = int(get_settings().douyin_goto_timeout_ms)
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=to,
        )
        human_delay(1.0, 2.5)
    except PlaywrightTimeout:
        out["error"] = "timeout"
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"goto: {e!s}"
        return out

    try:
        t = find_with_fallback(
            page,
            dsel.DETAIL_TITLE_SELECTORS,
            default=None,
            field_name="title",
            page_url=url,
        )
        if t and str(t).strip():
            out["title"] = str(t).strip()[:500]
        if not out["title"]:
            st0 = _safe_page_title(page)
            if st0:
                d = (st0.split("-", maxsplit=1)[0] or st0).strip()
                if d and "抖音" not in d:
                    out["title"] = d[:200]
        if not out["title"]:
            og = _meta_content(page, "meta[property='og:title']") or _meta_content(
                page, "meta[name='og:title']"
            )
            if og:
                out["title"] = og[:500]

        b = find_with_fallback(
            page,
            dsel.DETAIL_DESC_SELECTORS,
            default=None,
            field_name="body",
            page_url=url,
        )
        out["body"] = b[:20000] if b and str(b).strip() else None
        if not out.get("body"):
            ogd = _meta_content(page, "meta[property='og:description']")
            if ogd:
                out["body"] = ogd[:20000]

        lk = find_interaction_count_from_texts(
            page, dsel.LIKE_TEXT_SELECTORS, field_name="likes", page_url=url
        )
        cm = find_interaction_count_from_texts(
            page, dsel.COMMENT_TEXT_SELECTORS, field_name="comments", page_url=url
        )
        sh = find_interaction_count_from_texts(
            page, dsel.SHARE_TEXT_SELECTORS, field_name="shares", page_url=url
        )
        cl = find_interaction_count_from_texts(
            page, dsel.COLLECT_TEXT_SELECTORS, field_name="collects", page_url=url
        )

        rx: dict[str, int] = {"likes": 0, "comments": 0, "shares": 0, "collects": 0}
        whole = ""
        try:
            if not page.is_closed():
                whole = page.inner_text("body", timeout=12_000)[:60000]
        except Exception:  # noqa: BLE001
            whole = ""
        if whole:
            for key, pats in _BODY_NUM_PATTERNS.items():
                for pat in pats:
                    m = re.search(pat, whole)
                    if m and m.lastindex and m.group(1):
                        rx[key] = max(rx[key], _parse_count(m.group(1)))
                        break
        try:
            if not page.is_closed():
                html = (page.content() or "")[:200000]
                m = re.search(
                    r'(?:likeCount|digg_count|\"digg_count\")[\\":\s]+(\d+)', html, re.I
                )
                if m:
                    rx["likes"] = max(rx["likes"], int(m.group(1)))
                pu = _extract_play_url_from_html(html)
                if pu:
                    out["play_url"] = pu
                    out["video_download_url"] = pu
        except Exception:  # noqa: BLE001
            pass

        out["likes"] = max(lk or 0, rx["likes"])
        out["comments"] = max(cm or 0, rx["comments"])
        out["shares"] = max(sh or 0, rx["shares"])
        out["collects"] = max(cl or 0, rx["collects"])

        out["image_urls"] = collect_image_urls(
            page,
            selectors=dsel.IMG_SELECTORS,
            page_url=url,
            field_name="images",
            max_count=12,
        )
        if not out["image_urls"]:
            ogi = _meta_content(page, "meta[property='og:image']")
            if ogi.startswith("http"):
                out["image_urls"] = [ogi]
    except Exception as e:  # noqa: BLE001
        out["error"] = f"scrape: {e!s}"

    out["heat"] = heat_score(
        likes=int(out.get("likes") or 0),
        comments=int(out.get("comments") or 0),
        collects=int(out.get("collects") or 0),
        shares=int(out.get("shares") or 0),
    )
    return out


def _dy_home() -> str:
    return "https://www.douyin.com/"


class DouyinCrawler:
    """抖音 PC 站：搜索 → 视频详情，接口风格与脚本层一致。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def search(
        self,
        keyword: str,
        min_likes: int = 0,
        top_n: int = 10,
        *,
        max_hrefs: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        按关键词搜索，拉取视频详情，过滤 ``likes >= min_likes``，按点赞数降序取前 ``top_n`` 条。

        每条含：``title``、``likes``、``video_url``（作品页 URL）、
        以及 ``play_url`` / ``video_download_url``（若能从 HTML 解析到 mp4）、其它互动字段与 ``heat``。
        """
        s = self.settings
        cap = max_hrefs or int(s.douyin_search_max_hrefs)
        p = play_start()
        dy_st = s.storage_douyin if s.storage_douyin.exists() else None
        browser, context = new_browser_context(p, s, dy_st)
        items: list[dict[str, Any]] = []
        try:
            page = context.new_page()
            try:
                page.goto(_dy_home(), wait_until="domcontentloaded", timeout=60_000)
                human_delay(1.0, 1.5)
            except Exception as e:  # noqa: BLE001
                print(f"[douyin][warn] 预打开首页: {e}")
            u0 = search_url(keyword)
            page.goto(
                u0,
                wait_until="domcontentloaded",
                timeout=int(s.douyin_goto_timeout_ms),
            )
            human_delay(1.2, 2.0)
            _scroll_page(
                page, int(s.douyin_list_scroll), s.delay_min, s.delay_max
            )
            hrefs = _collect_video_hrefs(page, cap)
            if not hrefs:
                g = page.locator('a[href*="/video/"]')
                for i in range(min(g.count(), cap * 2)):
                    a = g.nth(i)
                    h = a.get_attribute("href")
                    n = _norm_douyin_video_url(h or "")
                    if n and n not in hrefs:
                        hrefs.append(n)
                    if len(hrefs) >= cap:
                        break

            for h in hrefs[:cap]:
                human_delay(s.delay_min, s.delay_max)
                sub = context.new_page()
                try:
                    data = _scrape_video_page(sub, h)
                    items.append(data)
                finally:
                    sub.close()
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
            p.stop()

        items = [x for x in items if int(x.get("likes") or 0) >= int(min_likes)]
        items.sort(
            key=lambda x: (int(x.get("likes") or 0), float(x.get("heat") or 0)),
            reverse=True,
        )
        return items[: int(top_n)]

    def download_videos(
        self, video_list: list[dict[str, Any]], save_dir: str | Path
    ) -> list[Path]:
        """
        根据 ``play_url`` / ``video_download_url`` 用 HTTP 落盘。无直链则跳过并打日志。
        """
        dest_root = Path(save_dir)
        dest_root.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for i, v in enumerate(video_list):
            src = (v.get("play_url") or v.get("video_download_url") or "").strip()
            if not src:
                print(
                    f"[douyin] 跳过无直链: {v.get('title', '')[:20]} {v.get('video_url', '')[:60]}"
                )
                continue
            name = f"{safe_slug((v.get('title') or f'video_{i}'))}_{i}.mp4"
            path = dest_root / name
            ok = download_file(
                src,
                path,
                referer="https://www.douyin.com/",
            )
            if ok:
                saved.append(path)
                print(f"[douyin] 已下载: {path.name}")
            else:
                print(f"[douyin] 下载失败: {src[:80]}…")
        return saved


def run_crawl_douyin(
    settings: Settings,
    keyword: str,
    top: int = 5,
    max_notes: int = 15,
    list_scroll: int = 3,
    search_sort: str = "general",
    min_heat: float = 0.0,
) -> list[dict[str, Any]]:
    """
    与 ``run_crawl`` 对接：在若干候选中按 ``heat`` 再取 TopN（与旧版行为一致）。
    ``search_sort`` 为占位，不影响排序（仍以详情 ``heat`` 为主）。
    """
    s = settings
    c = DouyinCrawler(s)
    # 与旧版一致：先按 max 条拉详情，再按 min_heat、再 heat Top
    p = play_start()
    dy_st = s.storage_douyin if s.storage_douyin.exists() else None
    browser, context = new_browser_context(p, s, dy_st)
    items: list[dict[str, Any]] = []
    try:
        try:
            page = context.new_page()
            try:
                page.goto(_dy_home(), wait_until="domcontentloaded", timeout=60_000)
                human_delay(1.0, 1.8)
            except Exception as e:  # noqa: BLE001
                print(f"[douyin][warn] 预打开首页: {e}")
            u0 = search_url(keyword)
            page.goto(
                u0,
                wait_until="domcontentloaded",
                timeout=int(s.douyin_goto_timeout_ms),
            )
            human_delay(1.5, 2.5)
            _scroll_page(
                page, int(list_scroll), s.delay_min, s.delay_max
            )
            hrefs = _collect_video_hrefs(page, max_notes)
            if not hrefs:
                g = page.locator('a[href*="/video/"]')
                for j in range(min(g.count(), max_notes * 2)):
                    a = g.nth(j)
                    h = a.get_attribute("href")
                    n = _norm_douyin_video_url(h or "")
                    if n and n not in hrefs:
                        hrefs.append(n)
                    if len(hrefs) >= max_notes:
                        break
            for h in hrefs[:max_notes]:
                human_delay(s.delay_min, s.delay_max)
                sub = context.new_page()
                try:
                    data = _scrape_video_page(sub, h)
                    items.append(data)
                finally:
                    sub.close()
        except Exception as e:  # noqa: BLE001
            print(f"[douyin][err] {e}")
    finally:
        try:
            context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        p.stop()
    if min_heat and min_heat > 0:
        items = [x for x in items if float(x.get("heat") or 0) >= min_heat]
    return top_n(items, top, "heat")
