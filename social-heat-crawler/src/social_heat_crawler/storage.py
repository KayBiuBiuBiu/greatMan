from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Any

import httpx


def safe_slug(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s)
    return s[:max_len] or "item"


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download_file(url: str, dest: Path, referer: str | None = None) -> bool:
    """用 httpx 拉取资源（比 urllib 好配 headers）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    if referer:
        headers["Referer"] = referer
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as c:
            r = c.get(url, headers=headers)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return True
    except Exception:
        return False


def download_file_urllib(url: str, dest: Path) -> bool:
    """备用：不依赖 httpx 证书问题时的简版。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            dest.write_bytes(r.read())
        return True
    except Exception:
        return False
