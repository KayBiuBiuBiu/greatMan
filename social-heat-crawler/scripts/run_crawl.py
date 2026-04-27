#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_heat_crawler.config import get_settings
from social_heat_crawler.crawlers.export_ops import demo_data, save_export
from social_heat_crawler.fingerprints import (
    filter_new,
    fingerprint_for_item,
    load_fingerprints,
    save_fingerprints,
)
from social_heat_crawler.scoring import heat_score, top_n
from social_heat_crawler.tracks import TRACK_KEYWORDS


def main() -> None:
    ap = argparse.ArgumentParser(description="按关键词爬取 + 热度 TopN 导出")
    ap.add_argument(
        "--platform",
        default="douyin",
        choices=("xiaohongshu", "douyin"),
        help="xiaohongshu=小红书；douyin=抖音（默认）",
    )
    ap.add_argument(
        "--keyword",
        default="",
        help="搜索关键词（与 --track / --food-pack 二选一或配合使用，见下）",
    )
    ap.add_argument(
        "--track",
        choices=sorted(TRACK_KEYWORDS.keys()),
        default=None,
        help="预置垂类；会展开为多子关键词（见 --food-pack）",
    )
    ap.add_argument(
        "--food-pack",
        action="store_true",
        help="使用预置「美食」多子关键词轮询（可配合 --track food）",
    )
    ap.add_argument(
        "--keywords",
        default="",
        help="逗号或空格分隔的多个关键词，会分别爬取后合并去重、再取 TopN",
    )
    ap.add_argument(
        "--search-sort",
        default="hot",
        help="搜索排序：综合 general | 最热 hot | 最新 new|latest（会尝试点 tab，失败仍按热度分排序）",
    )
    ap.add_argument("--max-notes", type=int, default=12, help="每轮最大详情页条数")
    ap.add_argument(
        "--list-scroll", type=int, default=4, help="结果列表页向下滚动轮数，便于加载更多卡片"
    )
    ap.add_argument(
        "--min-heat",
        type=float,
        default=0.0,
        help="最低热度分（在 TopN 之前过滤；0 表示不限制）",
    )
    ap.add_argument(
        "--dedup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="与本地指纹库去重（默认开）；仅导出未见过的笔记",
    )
    ap.add_argument(
        "--persist-fingerprints",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="将本次新笔记的指纹写入 data/seen_fingerprints.json（可关，仅过滤不落盘）",
    )
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument(
        "--demo",
        action="store_true",
        help="不拉真实页面，用示例数据走通排序与导出",
    )
    args = ap.parse_args()
    s = get_settings()
    s.export_path.mkdir(parents=True, exist_ok=True)

    if args.demo:
        demo_kw = (args.keyword or "").strip() or "demo"
        top_items = demo_data(demo_kw)
        out = save_export(top_items, s.export_path, demo_kw)
        print("DEMO 已导出到", out)
        return

    if args.platform == "xiaohongshu" and not s.storage_xhs.exists():
        print("缺少登录态: data/storage_state_xhs.json，请先: python scripts/save_login_state.py --platform xiaohongshu")
        raise SystemExit(1)
    if args.platform == "douyin" and not s.storage_douyin.exists():
        print("缺少登录态: data/storage_state_douyin.json，请先: python scripts/save_login_state.py --platform douyin")
        raise SystemExit(1)
    if args.platform not in ("xiaohongshu", "douyin"):
        print("--platform 仅支持: xiaohongshu | douyin")
        raise SystemExit(1)

    def _split_keywords(raw: str) -> list[str]:
        if not raw or not str(raw).strip():
            return []
        parts: list[str] = []
        for chunk in str(raw).replace(",", " ").split():
            t = chunk.strip()
            if t:
                parts.append(t)
        return parts

    kw_list: list[str] = []
    if args.food_pack or args.track == "food":
        kw_list = list(TRACK_KEYWORDS.get("food", []))
    custom = _split_keywords(args.keywords)
    if custom:
        kw_list = custom
    single = (args.keyword or "").strip()
    if not kw_list:
        if not single:
            print("请提供 --keyword，或 --food-pack，或 --keywords 'a b c'")
            raise SystemExit(1)
        kw_list = [single]

    fp_path = s.fingerprints_path
    seen = load_fingerprints(fp_path) if args.dedup else set()

    sort_raw = (args.search_sort or "hot").strip().lower()
    sort_map = {
        "综合": "general",
        "general": "general",
        "全部": "general",
        "最热": "hot",
        "hot": "hot",
        "hottest": "hot",
        "最新": "time",
        "新": "time",
        "new": "time",
        "latest": "time",
        "time": "time",
    }
    search_sort = sort_map.get(sort_raw, sort_raw)
    if search_sort not in ("general", "hot", "time"):
        print("未知的 --search-sort，已回退为 hot；可用 general / hot / new")
        search_sort = "hot"

    merged: list[dict] = []
    for kw in kw_list:
        if args.platform == "xiaohongshu":
            from social_heat_crawler.crawlers.xhs_crawler import run_crawl

            batch = run_crawl(
                s,
                kw,
                top=max(args.max_notes, args.top * 3),
                max_notes=args.max_notes,
                list_scroll=args.list_scroll,
                search_sort=search_sort,
                min_heat=args.min_heat,
            )
        else:
            from social_heat_crawler.crawlers.douyin_crawler import run_crawl_douyin

            batch = run_crawl_douyin(
                s,
                kw,
                top=max(args.max_notes, args.top * 3),
                max_notes=args.max_notes,
                list_scroll=args.list_scroll,
                search_sort=search_sort,
                min_heat=args.min_heat,
            )
        for it in batch:
            it.setdefault("search_keyword", kw)
        merged.extend(batch)

    # 多关键词合并后：先去重，再全量按热度取 TopN
    if args.dedup:
        fresh, new_fps, dups = filter_new(merged, seen)
        print(
            f"去重：候选 {len(merged)} 条，重复 {len(dups)} 条，"
            f"新笔记 {len(fresh)} 条（指纹库 {len(seen)}）"
        )
        merged = fresh
        if args.persist_fingerprints and new_fps:
            save_fingerprints(fp_path, seen | new_fps)
    else:
        for it in merged:
            it["fingerprint"] = fingerprint_for_item(it)

    for it in merged:
        it["heat"] = heat_score(
            likes=int(it.get("likes") or 0),
            comments=int(it.get("comments") or 0),
            collects=int(it.get("collects") or 0),
            shares=int(it.get("shares") or 0),
        )

    top_items = top_n(merged, args.top, "heat")
    if not top_items:
        print("未爬到任何笔记，可能选择器失效或需登录。可用 --demo 试流程。")
        raise SystemExit(2)
    export_label = single or ("_".join(kw_list[:3]) + ("_等" if len(kw_list) > 3 else ""))
    out = save_export(top_items, s.export_path, export_label)
    print("完成，导出目录：", out)


if __name__ == "__main__":
    main()
