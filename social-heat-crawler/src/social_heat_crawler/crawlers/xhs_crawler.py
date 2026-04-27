from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..human import human_delay
from ..scoring import heat_score, top_n
from . import selectors_xhs as sel
from .base import new_browser_context, play_start
from .selectors_xhs import (
    collect_image_urls,
    find_interaction_count_from_texts,
    find_with_fallback,
    parse_count_text,
)

# 与旧逻辑兼容：正文区正则补抓互动数
_METRIC_PATTERNS = [
    ("likes", r"赞[：\s]*(\d+\.?\d*万|\d+)"),
    ("comments", r"评论[：\s]*(\d+\.?\d*万|\d+)"),
    ("collects", r"收藏[：\s]*(\d+\.?\d*万|\d+)"),
]


def _parse_count(s: str) -> int:
    """与 parse_count_text 同义，供正则分支使用。"""
    return parse_count_text(s)


def _search_url_with_query(
    path_with_qmark: str, params: dict[str, str]
) -> str:
    """path_with_qmark 为 https://.../search_result? 或 .../search_result/?"""
    return path_with_qmark + urllib.parse.urlencode(params)


def _search_url_candidates(keyword: str, settings: Settings) -> list[str]:
    """
    搜索页入口。说明：
    - 在部分浏览器/未登录/风控下，带 `source=web_search_result_notes` 或 URL 里带 `sort=`
      会返回「你访问的页面不见了」；故优先极简 keyword，排序交给 _try_click_search_sort_tab。
    - 多候选给 Playwright 自动重试，提高命中率。
    """
    mode = (settings.xhs_search_url_mode or "try_all").lower().strip()
    minimal = _search_url_with_query(
        "https://www.xiaohongshu.com/search_result?", {"keyword": keyword}
    )
    legacy = _search_url_with_query(
        "https://www.xiaohongshu.com/search_result?",
        {"keyword": keyword, "source": "web_search_result_notes"},
    )
    slash = _search_url_with_query(
        "https://www.xiaohongshu.com/search_result/?", {"keyword": keyword}
    )
    if mode == "minimal":
        return [minimal]
    if mode == "legacy":
        return [legacy, minimal]
    # try_all：最稳的放最前
    return [minimal, legacy, slash]


def search_url(keyword: str, search_sort: str = "general") -> str:
    """
    返回**首选**搜索地址（兼容旧代码）。不在 URL 中带 sort，避免 404；排序在页面上点 tab。
    """
    from ..config import get_settings

    s = get_settings()
    cands = _search_url_candidates(keyword, s)
    if cands:
        return cands[0]
    return _search_url_with_query(
        "https://www.xiaohongshu.com/search_result?", {"keyword": keyword}
    )


def _try_click_search_sort_tab(page: Any, search_sort: str) -> None:
    """在搜索结果页点「综合 / 最新 / 最热」之一，失败则忽略。"""
    mode = (search_sort or "general").lower().strip()
    labels: list[str] = []
    if mode in ("hot", "hottest", "最热"):
        labels = ["最热", "熱門"]
    elif mode in ("time", "time_desc", "new", "latest", "newest", "最新"):
        labels = ["最新"]
    else:
        labels = ["综合", "全部", "推薦"]

    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    for text in labels:
        try:
            b = page.get_by_role("button", name=text)
            if b.count() and b.first.is_visible():
                b.first.click(timeout=3_000)
                human_delay(0.6, 1.4)
                return
        except (PlaywrightTimeout, Exception):  # noqa: BLE001
            pass
        try:
            link = page.get_by_role("link", name=text)
            if link.count() and link.first.is_visible():
                link.first.click(timeout=3_000)
                human_delay(0.6, 1.4)
                return
        except (PlaywrightTimeout, Exception):  # noqa: BLE001
            pass
        try:
            tab = page.get_by_text(text, exact=True)
            if tab.count():
                t0 = tab.first
                if t0.is_visible():
                    t0.click(timeout=3_000)
                    human_delay(0.6, 1.4)
                    return
        except (PlaywrightTimeout, Exception):  # noqa: BLE001
            continue


def _scroll_page(page: Any, times: int, dmin: float, dmax: float) -> None:
    for _ in range(times):
        page.mouse.wheel(0, 1200)
        human_delay(dmin, dmax)


def _collect_note_hrefs(page: Any, limit: int) -> list[str]:
    """搜索页：多组 a 选择器去重，尽量收集 /explore/ 笔记链接。"""
    hrefs: list[str] = []
    for sel_css in sel.NOTE_LINK_SELECTORS:
        try:
            group = page.locator(sel_css)
            for i in range(group.count()):
                a = group.nth(i)
                h = a.get_attribute("href")
                if h and ("/explore/" in h or "discovery/item" in h):
                    if h.startswith("/"):
                        h = "https://www.xiaohongshu.com" + h
                    if h not in hrefs:
                        hrefs.append(h)
        except Exception:  # noqa: BLE001
            continue
    return hrefs[:limit]


def _safe_page_title(page: Any) -> str:
    """部分异常页/崩溃页/重定向中 `page.title()` 会抛错，勿让整次任务中断。"""
    try:
        t = page.title()
        return (t or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _xhs_is_gone_or_not_found(page: Any) -> bool:
    """检测站点「你访问的页面不见了」等 404/拦截页（与正常搜索页区分）。"""
    t = _safe_page_title(page)
    if t and ("页面不见了" in t or "你访问的页面" in t):
        return True
    try:
        b = page.locator("body")
        if b.count() == 0:
            return False
        tx = (b.first.inner_text(timeout=6_000) or "")[:5000]
        if "你访问的页面不见了" in tx and "返回上一页" in tx:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _meta_content(page: Any, css: str) -> str:
    try:
        loc = page.locator(css)
        if loc.count() == 0:
            return ""
        c = loc.first.get_attribute("content")
        return (c or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _fallback_og_title(page: Any) -> str:
    for css in (
        "meta[property='og:title']",
        "meta[name='og:title']",
        "meta[name='twitter:title']",
    ):
        s = _meta_content(page, css)
        if s:
            return s
    return ""


def _fallback_og_description(page: Any) -> str:
    for css in (
        "meta[property='og:description']",
        "meta[name='description']",
        "meta[name='twitter:description']",
    ):
        s = _meta_content(page, css)
        if s:
            return s
    return ""


def _scrape_note_page(page: Any, url: str, referer: str) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    out: dict[str, Any] = {
        "url": url,
        "title": None,
        "body": None,
        "likes": 0,
        "comments": 0,
        "collects": 0,
        "shares": 0,
        "image_urls": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "platform": "xiaohongshu",
    }
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        human_delay(1.2, 3.0)
    except PlaywrightTimeout:
        out["error"] = "timeout"
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"goto: {e!s}"
        return out

    try:
        # 标题：多选 CSS → document.title / og:title
        t = find_with_fallback(
            page,
            sel.DETAIL_TITLE_SELECTORS,
            default=None,
            field_name="title",
            page_url=url,
        )
        if t and str(t).strip():
            out["title"] = str(t).strip()[:500]
        if not out["title"]:
            doc_title = _safe_page_title(page)
            if doc_title and doc_title not in ("小红书", "Xiaohongshu"):
                out["title"] = doc_title[:200]
        if not out["title"]:
            og_t = _fallback_og_title(page)
            if og_t:
                out["title"] = og_t[:500]

        b = find_with_fallback(
            page,
            sel.DETAIL_DESC_SELECTORS,
            default=None,
            field_name="body",
            page_url=url,
        )
        out["body"] = b[:20000] if b and str(b).strip() else None
        if not out["body"] or not str(out["body"]).strip():
            og_d = _fallback_og_description(page)
            if og_d:
                out["body"] = og_d[:20000]

        # 互动数：交互区解析（可能为 None）与正文可见文本正则取 max，避免只依赖单一路径
        lk = find_interaction_count_from_texts(
            page, sel.LIKE_TEXT_SELECTORS, field_name="likes", page_url=url
        )
        cm = find_interaction_count_from_texts(
            page, sel.COMMENT_TEXT_SELECTORS, field_name="comments", page_url=url
        )
        cl = find_interaction_count_from_texts(
            page, sel.COLLECT_TEXT_SELECTORS, field_name="collects", page_url=url
        )
        rx: dict[str, int] = {"likes": 0, "comments": 0, "collects": 0}
        try:
            if page.is_closed():
                out["error"] = "page_closed"
                return out
            whole = page.inner_text("body", timeout=15_000)[:50000]
            for name, pat in _METRIC_PATTERNS:
                m = re.search(pat, whole)
                if m:
                    n = _parse_count(m.group(1))
                    rx[name] = max(rx[name], n)
        except Exception:  # noqa: BLE001
            try:
                whole2 = (page.content() or "")[:80000]
                for name, pat in _METRIC_PATTERNS:
                    m = re.search(pat, whole2)
                    if m:
                        n = _parse_count(m.group(1))
                        rx[name] = max(rx[name], n)
            except Exception:  # noqa: BLE001
                pass
        out["likes"] = max(lk or 0, rx["likes"])
        out["comments"] = max(cm or 0, rx["comments"])
        out["collects"] = max(cl or 0, rx["collects"])

        out["image_urls"] = collect_image_urls(
            page, page_url=url, field_name="images", max_count=12
        )
        if not out["image_urls"]:
            ogi = _meta_content(page, "meta[property='og:image']")
            if ogi.startswith("http"):
                out["image_urls"] = [ogi]
    except Exception as e:  # noqa: BLE001
        out["error"] = f"scrape: {e!s}"
    return out


def run_crawl(
    settings: Settings,
    keyword: str,
    top: int = 5,
    max_notes: int = 15,
    list_scroll: int = 3,
    search_sort: str = "general",
    min_heat: float = 0.0,
) -> list[dict[str, Any]]:
    p = play_start()
    browser, context = new_browser_context(p, settings, settings.storage_xhs)
    page = context.new_page()
    items: list[dict[str, Any]] = []
    # 与 Codegen/桌面态一致时：先经首页让 Cookie 在站点内有效，直进 search_result 易被 404
    _XHS_HOME = "https://www.xiaohongshu.com"
    try:
        page.goto(_XHS_HOME, wait_until="domcontentloaded", timeout=60_000)
        human_delay(1.2, 2.2)
        if _xhs_is_gone_or_not_found(page):
            print("[xhs][warn] 首页也显示「页面不见了」：多为登录态与当前浏览器环境不一致，"
                  "或 cookie 已失效。请让 .env 中 SHT_XHS_EMULATE_MOBILE 与保存 storage 时一致，并重登。")
    except Exception as e:  # noqa: BLE001
        print(f"[xhs][warn] 预打开首页失败（将仍尝试搜索）：{e}")

    try:
        cands = _search_url_candidates(keyword, settings)
        opened = False
        u = cands[0] if cands else search_url(keyword, search_sort=search_sort)
        for entry in cands:
            try:
                page.goto(
                    entry, wait_until="domcontentloaded", timeout=90_000
                )
                human_delay(1.6, 3.0)
                if _xhs_is_gone_or_not_found(page):
                    print(
                        "[xhs][warn] 该搜索地址返回「你访问的页面不见了」，将尝试下一入口。 "
                        f"url={entry[:100]}"
                    )
                    continue
                u = entry
                opened = True
                break
            except Exception as e:  # noqa: BLE001
                print(
                    f"[xhs][warn] 打开 search_result 失败，尝试下一入口：{e!s} | url={entry[:100]}"
                )
        if cands and not opened:
            print(
                "[xhs][err] 所有 search_result 候选均不可用（404/风控/网络）。请确认：\n"
                "  1) data/storage_state_xhs.json 为最近登录、未过期；\n"
                "  2) .env 中 SHT_XHS_EMULATE_MOBILE 与**保存此文件时**一致："
                "playwright codegen（桌面）=0；save_login 移动模拟=1；\n"
                "  3) 在 .env 中尝试 SHT_XHS_SEARCH_URL_MODE=minimal；\n"
                "  4) 关 VPN、降低爬取频率。"
            )
            page.goto(cands[0], wait_until="domcontentloaded", timeout=90_000)
            human_delay(2, 4)
        elif not cands:
            u = search_url(keyword, search_sort=search_sort)
            page.goto(u, wait_until="domcontentloaded", timeout=90_000)
            human_delay(2, 4)

        _try_click_search_sort_tab(page, search_sort)
        _scroll_page(page, list_scroll, settings.delay_min, settings.delay_max)
        hrefs = _collect_note_hrefs(page, max_notes)
        if not hrefs:
            g = page.locator('a[href*="/explore/"]')
            for i in range(min(g.count(), max_notes * 2)):
                a = g.nth(i)
                h = a.get_attribute("href")
                if h:
                    if h.startswith("/"):
                        h = "https://www.xiaohongshu.com" + h
                    if h not in hrefs and "?" not in h[:50]:
                        hrefs.append(h)
                if len(hrefs) >= max_notes:
                    break

        referer = u
        for i, h in enumerate(hrefs):
            if i >= max_notes:
                break
            human_delay(settings.delay_min, settings.delay_max)
            sub = context.new_page()
            try:
                data = _scrape_note_page(sub, h, referer)
                data["heat"] = heat_score(
                    likes=int(data.get("likes") or 0),
                    comments=int(data.get("comments") or 0),
                    collects=int(data.get("collects") or 0),
                )
                items.append(data)
            finally:
                sub.close()
    finally:
        context.close()
        browser.close()
        p.stop()

    if min_heat and min_heat > 0:
        items = [x for x in items if float(x.get("heat") or 0) >= min_heat]
    return top_n(items, top, "heat")
