"""BK 解析：config 覆盖、磁盘 by_code 缓存（无网络）。"""

from __future__ import annotations

import json
from pathlib import Path

from sector_em import resolve_sector_bk


def test_sector_index_override_returns_bk(tmp_path: Path, merged_cfg: dict) -> None:
    cfg = dict(merged_cfg)
    cfg["sector_index_overrides"] = {"600000": "BK0475"}
    bk = resolve_sector_bk("600000", "sh", cfg, root=tmp_path)
    assert bk == "BK0475"


def test_disk_by_code_cache_returns_bk(tmp_path: Path, merged_cfg: dict) -> None:
    cfg = dict(merged_cfg)
    cfg["sector_index_overrides"] = {}
    cfg["sector_em"] = dict(cfg.get("sector_em") or {})
    cfg["sector_em"]["cache_filename"] = "test_sector_cache.json"
    cache_path = tmp_path / "test_sector_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "by_code": {"600036": "BK0475"},
                "industry_name_to_bk": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bk = resolve_sector_bk("600036", "sh", cfg, root=tmp_path)
    assert bk == "BK0475"
