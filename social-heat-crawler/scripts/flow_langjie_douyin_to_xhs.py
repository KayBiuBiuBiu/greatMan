#!/usr/bin/env python3
"""
一键：用抖音搜索「浪姐」相关作品 → 导出 TopN；再自动打开发布页，把 Top1 的**文案+本地封面图**发到小红书。

说明（必读）：
- 爬取走 **抖音**（需 `data/storage_state_douyin.json`）。
- 发布走 **小红书**（需 `data/storage_state_xhs.json`），与抖音不是同一套登录。
- 导出的是**封面图 + 标题/描述**，**不是**把抖音短视频原片搬运过去；要发原视频到抖音，须自行下载后去 creator.douyin.com 上传（本仓库未内建视频下载）。

用法：
  python scripts/flow_langjie_douyin_to_xhs.py
  python scripts/flow_langjie_douyin_to_xhs.py --skip-crawl          # 只用最新一次导出发小红书
  python scripts/flow_langjie_douyin_to_xhs.py --item-index 2     # 发导出的第 2 条
  python scripts/flow_langjie_douyin_to_xhs.py --manual            # 只填表不自动点「发布」
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 多词轮询，提高命中（可按需改）
DEFAULT_KEYWORDS = "浪姐,乘风破浪,姐姐"
DEFAULT_TOP = 5


def main() -> None:
    ap = argparse.ArgumentParser(description="浪姐：抖音爬取 + 小红书自动发布（图文）")
    ap.add_argument("--skip-crawl", action="store_true", help="跳过爬取，只用 exports 里最新一批")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="逗号/空格分隔，传给 run_crawl --keywords")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP)
    ap.add_argument("--item-index", type=int, default=1, help="发第几条（1=Top1）")
    ap.add_argument("--manual", action="store_true", help="不自动点小红书「发布」")
    args = ap.parse_args()

    s_py = sys.executable
    rc = ROOT / "scripts" / "run_crawl.py"
    rp = ROOT / "scripts" / "run_prepare_publish.py"

    if not args.skip_crawl:
        print("=== 1/2 抖音爬取：", args.keywords, "===")
        r = subprocess.run(
            [
                s_py,
                str(rc),
                "--platform",
                "douyin",
                "--keywords",
                args.keywords,
                "--top",
                str(args.top),
            ],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            print("爬取未成功，已中止；可用 --skip-crawl 仅重试发布。")
            raise SystemExit(r.returncode or 1)

    print("=== 2/2 小红书发布（使用本次或最近一次导出） ===")
    cmd = [
        s_py,
        str(rp),
        "--platform",
        "xiaohongshu",
        "--item-index",
        str(args.item_index),
    ]
    if args.manual:
        cmd.append("--manual")
    r2 = subprocess.run(cmd, cwd=str(ROOT))
    raise SystemExit(r2.returncode or 0)


if __name__ == "__main__":
    main()
