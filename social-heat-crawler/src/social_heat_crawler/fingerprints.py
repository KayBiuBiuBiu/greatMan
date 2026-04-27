"""笔记去重：用标题片段 + 首图 URL 生成稳定指纹，持久化在本地 JSON。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_FP_PATH = "data/seen_fingerprints.json"


def _norm_title(s: str | None) -> str:
    t = (s or "").strip()
    return t[:40]


def _first_image(urls: list[str] | None) -> str:
    if not urls:
        return ""
    for u in urls:
        if u and str(u).strip().startswith("http"):
            return str(u).strip()
    return ""


def fingerprint_for_item(item: dict[str, Any]) -> str:
    """
    对同一篇笔记，标题/封面在列表与详情里往往一致，组合后可减少重复。
    若无首图，则退化为「标题+URL」。
    """
    title = _norm_title(item.get("title") if isinstance(item, dict) else None)
    imgs = item.get("image_urls") if isinstance(item, dict) else None
    if not isinstance(imgs, list):
        imgs = []
    first = _first_image([str(x) for x in imgs])
    u = (item.get("url") or "") if isinstance(item, dict) else ""
    raw = f"{title}\n{first or u}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_fingerprints(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    if isinstance(data, list):
        return {str(x) for x in data if x}
    if isinstance(data, dict) and "fingerprints" in data:
        v = data.get("fingerprints")
        if isinstance(v, list):
            return {str(x) for x in v if x}
    return set()


def save_fingerprints(path: Path, fps: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"fingerprints": sorted(fps)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def filter_new(
    items: list[dict[str, Any]], seen: set[str]
) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    new_items: list[dict[str, Any]] = []
    dups: list[dict[str, Any]] = []
    added: set[str] = set()
    for it in items:
        fp = fingerprint_for_item(it)
        it["fingerprint"] = fp
        if fp in seen or fp in added:
            dups.append(it)
            continue
        added.add(fp)
        new_items.append(it)
    return new_items, added, dups
