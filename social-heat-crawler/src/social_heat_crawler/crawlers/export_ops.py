"""导出与 DEMO 数据（不依赖 Playwright，便于无浏览器环境试跑）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..scoring import heat_score, top_n
from ..storage import download_file, safe_slug, save_json


def save_export(
    top_items: list[dict[str, Any]], export_dir: Path, keyword: str
) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    run_dir = export_dir / safe_slug(
        f"{keyword}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    save_json(
        {
            "keyword": keyword,
            "count": len(top_items),
            "items": top_items,
        },
        run_dir / "crawl_result.json",
    )
    for idx, it in enumerate(top_items):
        folder = run_dir / f"top{idx+1}_{safe_slug(it.get('title') or f'note_{idx}')}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.txt").write_text(
            f"标题: {it.get('title','')}\n"
            f"平台: {it.get('platform','')}\n"
            f"原文摘要: {(it.get('body') or '')[:800]}\n"
            f"源链接: {it.get('url','')}\n",
            encoding="utf-8",
        )
        ref = (
            "https://www.douyin.com/"
            if it.get("platform") == "douyin"
            else "https://www.xiaohongshu.com/"
        )
        for j, u in enumerate(it.get("image_urls") or []):
            if not u:
                continue
            ext = "jpg" if "jpg" in u or "jpeg" in u else "png" if "png" in u else "bin"
            pth = folder / f"img_{j}.{ext}"
            ok = download_file(u, pth, referer=ref)
            if not ok:
                pth.write_text(f"请手动下载: {u}\n", encoding="utf-8")
    return run_dir


def demo_data(keyword: str) -> list[dict[str, Any]]:
    base: list[dict[str, Any]] = []
    for i in range(6):
        base.append(
            {
                "url": f"https://example.com/demo/{i}",
                "title": f"[DEMO] {keyword} 示例{i+1}",
                "body": "请替换为真实抓到的正文。本条目仅用于测试热度排序与目录导出。",
                "likes": 1000 - i * 100,
                "comments": 50 + i * 20,
                "collects": 20 + i * 5,
                "image_urls": [],
                "heat": 0.0,
            }
        )
        base[-1]["heat"] = heat_score(
            likes=base[-1]["likes"],
            comments=base[-1]["comments"],
            collects=base[-1]["collects"],
        )
    return top_n(base, 5, "heat")
