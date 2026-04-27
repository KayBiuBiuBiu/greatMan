#!/usr/bin/env python3
"""
对 data/exports 下最新批次 meta.txt 做**浅层同义替换**（示例，非大模型）。

真正二创请人工改或用你自己的 API。本脚本仅作「不原样搬运」的提醒与占位。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data" / "exports"


# 极少量同义词，避免与原文 100% 相同；你可换成调用 OpenAI/Claude 等
_REPLACEMENTS = [
    ("非常", "挺"),
    ("其实", "说起来"),
    ("可以", "能够"),
    ("因为", "由于"),
    ("但是", "不过"),
]


def rough_rewrite(text: str) -> str:
    t = text
    for a, b in _REPLACEMENTS:
        t = t.replace(a, b, 1)  # 每对只替换一次，减少面目全非
    t = t.strip()
    if t and not t.startswith("【二创草稿】"):
        t = "【二创草稿】" + t
    return t


def main() -> None:
    if not EXPORT.exists():
        print("无 exports 目录，先运行 run_crawl")
        raise SystemExit(1)
    batches = sorted(
        [p for p in EXPORT.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not batches:
        print("无导出批次")
        raise SystemExit(1)
    latest = batches[0]
    for meta in latest.glob("**/meta.txt"):
        raw = meta.read_text(encoding="utf-8")
        # 只处理「摘要」行后内容可再细化；此处整段浅改
        out = meta.with_name("meta_rewrite.txt")
        out.write_text(rough_rewrite(raw), encoding="utf-8")
        print("已写", out)
    print("请人工审阅后使用，勿直接全量发。")


if __name__ == "__main__":
    main()
