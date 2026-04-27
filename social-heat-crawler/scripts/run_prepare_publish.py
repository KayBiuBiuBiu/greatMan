#!/usr/bin/env python3
"""半自动发布：xiaohongshu=填文+传图+可自动点发；douyin=打开发布页+填标题+等人上传。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_heat_crawler.config import get_settings
from social_heat_crawler.publish.douyin_open_upload import open_douyin_upload_and_fill_title
from social_heat_crawler.publish.xhs_open_creator import publish_note


def _latest_batch_dir(export_dir: Path) -> Path | None:
    if not export_dir.exists():
        return None
    dirs = [p for p in export_dir.iterdir() if p.is_dir()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0]


def _batch_dirs_newest_first(export_dir: Path) -> list[Path]:
    if not export_dir.exists():
        return []
    dirs = [p for p in export_dir.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs


def _crawl_data_has_items(batch_dir: Path) -> bool:
    jpath = batch_dir / "crawl_result.json"
    if not jpath.exists():
        return False
    try:
        data = json.loads(jpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("items"))


def _resolve_douyin_batch_dir(s, batch_arg: str) -> Path:
    """取导出目录：优先有 items 的批次（自新向旧扫）；都没有则用最新目录（配合 --title / keyword）。"""
    if batch_arg:
        p = Path(batch_arg)
        if not p.is_dir():
            raise FileNotFoundError(f"batch-dir 不是目录: {p}")
        return p
    out = s.douyin_export_path
    batches = _batch_dirs_newest_first(out)
    if not batches:
        raise FileNotFoundError("data/exports/douyin 下无子目录，请先跑 crawl_douyin.py")
    for b in batches:
        if _crawl_data_has_items(b):
            if b is not batches[0]:
                print(
                    f"[publish][dy] 最新子目录 {batches[0].name!r} 的 items 为空，"
                    f"改用有数据的批次: {b.name}"
                )
            return b
    print(
        f"[publish][dy] 警告: {out} 下各批次的 items 均为空，"
        "将仅用 --title 或 crawl_result 里的 keyword 填标题。请先降低 --min-likes 或重跑爬取。"
    )
    return batches[0]


def _load_item_from_batch(batch_dir: Path, item_index: int) -> dict:
    jpath = batch_dir / "crawl_result.json"
    if not jpath.exists():
        raise FileNotFoundError(f"未找到 {jpath}")
    data = json.loads(jpath.read_text(encoding="utf-8"))
    items = data.get("items") or []
    if not items:
        raise ValueError("crawl_result.json 中 items 为空")
    idx = max(1, item_index) - 1
    if idx >= len(items):
        raise IndexError(f"item-index 超出范围：{item_index} > {len(items)}")
    return items[idx]


def _guess_item_media_dir(batch_dir: Path, item_index: int) -> Path | None:
    prefix = f"top{item_index}_"
    candidates = [p for p in batch_dir.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    if candidates:
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    tops = [p for p in batch_dir.iterdir() if p.is_dir() and p.name.startswith("top")]
    tops.sort(key=lambda p: p.name)
    idx = max(1, item_index) - 1
    if idx < len(tops):
        return tops[idx]
    return None


def _collect_local_images(item_dir: Path | None) -> list[Path]:
    if item_dir is None or (not item_dir.exists()):
        return []
    imgs: list[Path] = []
    for pat in ("img_*.jpg", "img_*.jpeg", "img_*.png", "img_*.webp"):
        imgs.extend(sorted(item_dir.glob(pat)))
    return imgs


def _resolve_xhs_batch_dir(s, batch_arg: str) -> Path:
    if batch_arg:
        return Path(batch_arg)
    d = _latest_batch_dir(s.export_path)
    if d is None:
        raise FileNotFoundError("data/exports 下无子目录，请先 run_crawl")
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description="半自动发布：小红书 / 抖音")
    ap.add_argument(
        "--platform",
        choices=("xiaohongshu", "douyin"),
        default="xiaohongshu",
    )
    ap.add_argument(
        "--batch-dir",
        default="",
        help="导出批次目录；抖音会去「有 items 的最新批次」，小红书取 exports 下最新子目录",
    )
    ap.add_argument("--item-index", type=int, default=1, help="第几条（从1，对应 items[]）")
    ap.add_argument("--title", default="", help="覆盖标题")
    ap.add_argument("--content", default="", help="仅小红书：覆盖正文")
    ap.add_argument(
        "--manual",
        action="store_true",
        help="仅小红书：不自动点「发布」",
    )
    args = ap.parse_args()
    s = get_settings()
    item: dict
    title: str
    batch_dir: Path

    if args.platform == "douyin":
        try:
            batch_dir = _resolve_douyin_batch_dir(
                s, (args.batch_dir or "").strip()
            )
        except FileNotFoundError as e:
            print(e)
            raise SystemExit(1)
        if not batch_dir.exists():
            print("batch-dir 不存在：", batch_dir)
            raise SystemExit(1)
        jpath = batch_dir / "crawl_result.json"
        if not jpath.exists():
            print(f"未找到 {jpath}")
            raise SystemExit(1)
        try:
            data = json.loads(jpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print("读取 JSON 失败：", e)
            raise SystemExit(1)
        items = data.get("items") or []
        if items:
            idx = max(1, args.item_index) - 1
            if idx >= len(items):
                print(f"item-index 超出范围：{args.item_index} > {len(items)}")
                raise SystemExit(1)
            item = items[idx]
        else:
            item = {"title": ""}
        # --title 优先；否则第 item-index 条 title；无 items 时用 crawl 的 keyword
        title = (args.title or item.get("title") or "").strip()
        if not title:
            title = (data.get("keyword") or "").strip()
        if not title:
            title = "今日分享"
            print(
                f"[publish][dy] 提示: 本批次无可用标题，已用占位「{title}」；请用 --title 或先爬出有效 items"
            )
    else:
        try:
            batch_dir = _resolve_xhs_batch_dir(
                s, (args.batch_dir or "").strip()
            )
        except FileNotFoundError as e:
            print(e)
            raise SystemExit(1)
        if not batch_dir.exists():
            print("batch-dir 不存在：", batch_dir)
            raise SystemExit(1)
        try:
            item = _load_item_from_batch(batch_dir, args.item_index)
        except Exception as e:
            print("读取 crawl_result.json 失败：", e)
            raise SystemExit(1)
        title = (args.title or item.get("title") or "").strip()
        if not title:
            title = "今日分享"

    if args.platform == "douyin":
        if not s.storage_douyin.exists():
            print("请保存抖音登录: python scripts/save_login_state.py --platform douyin")
            raise SystemExit(1)
        print(f"[publish][dy] 批次: {batch_dir}")
        print(f"[publish][dy] 条目: #{args.item_index}  标题: {title[:50]}")
        print(f"[publish][dy] 发布页: {s.douyin_creator_upload_url}（只填标题，不自动上传）")
        ok = open_douyin_upload_and_fill_title(s, title=title)
        raise SystemExit(0 if ok else 2)

    if not s.storage_xhs.exists():
        print("请先: python scripts/save_login_state.py --platform xiaohongshu")
        raise SystemExit(1)
    content = (args.content or item.get("body") or "").strip() or "灵感记录。"
    item_dir = _guess_item_media_dir(batch_dir, args.item_index)
    images = _collect_local_images(item_dir)
    print(f"[publish] 批次目录: {batch_dir}")
    print(f"[publish] 选择条目: Top{args.item_index}")
    print(f"[publish] 图片数量: {len(images)}")

    ok = publish_note(
        s,
        title=title,
        content=content,
        image_paths=images,
        auto_submit=not args.manual,
    )
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
