#!/usr/bin/env python3
"""抖音：按关键词搜索、过滤点赞、导出到 data/exports/douyin/。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_heat_crawler.config import get_settings
from social_heat_crawler.crawlers.douyin_crawler import DouyinCrawler
from social_heat_crawler.storage import save_json, safe_slug


def main() -> int:
    ap = argparse.ArgumentParser(description="抖音爬取并导出到 data/exports/douyin/")
    ap.add_argument("--keyword", required=True, help="搜索关键词")
    ap.add_argument(
        "--min-likes", type=int, default=0, help="最低点赞数（基于详情页解析值）"
    )
    ap.add_argument("--top", type=int, default=10, help="返回前 N 条")
    ap.add_argument(
        "--download",
        action="store_true",
        help="尝试用 play_url 直链下载 mp4 到同批次 videos/（常因无直链而跳过）",
    )
    args = ap.parse_args()

    s = get_settings()
    if not s.storage_douyin.exists():
        print("请先: python scripts/save_login_state.py --platform douyin")
        return 1

    s.douyin_export_path.mkdir(parents=True, exist_ok=True)
    run_id = f"{args.keyword}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    out_dir = s.douyin_export_path / safe_slug(run_id, max_len=60)
    out_dir.mkdir(parents=True, exist_ok=True)

    crawler = DouyinCrawler(s)
    print(f"搜索: {args.keyword!r}  min_likes>={args.min_likes}  top={args.top} …")
    items = crawler.search(
        args.keyword, min_likes=args.min_likes, top_n=args.top
    )
    payload = {
        "keyword": args.keyword,
        "min_likes": args.min_likes,
        "top": args.top,
        "count": len(items),
        "items": items,
    }
    save_json(payload, out_dir / "crawl_result.json")
    print(f"已保存: {out_dir / 'crawl_result.json'}")

    if not items:
        print(
            "提示: items 为空（无符合 min_likes 的条目或页面上未解析到视频）。"
            "可试：降低 --min-likes 或换 --keyword。run_prepare_publish 可用 --title 或含 keyword 的批次。"
        )

    if args.download and items:
        vdir = out_dir / "videos"
        n = len(crawler.download_videos(items, vdir))
        print(f"成功下载 {n} 个文件到 {vdir}/")

    return 0 if items else 2


if __name__ == "__main__":
    raise SystemExit(main())
