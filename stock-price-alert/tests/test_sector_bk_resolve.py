"""申万板块解析：config 覆盖、磁盘 by_code、stock_to_sw（无东财）。"""

from __future__ import annotations

import json
from pathlib import Path

from sector_em import resolve_sector_bk


def test_sector_index_override_returns_sw(tmp_path: Path, merged_cfg: dict) -> None:
    cfg = dict(merged_cfg)
    cfg["sector_index_overrides"] = {"600000": "801780.SI"}
    bk = resolve_sector_bk("600000", "sh", cfg, root=tmp_path)
    assert bk == "801780.SI"


def test_disk_by_code_cache_returns_sw(tmp_path: Path, merged_cfg: dict) -> None:
    cfg = dict(merged_cfg)
    cfg["sector_index_overrides"] = {}
    cfg["sector_em"] = dict(cfg.get("sector_em") or {})
    cfg["sector_em"]["cache_filename"] = "test_sector_cache.json"
    cache_path = tmp_path / "test_sector_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 2,
                "by_code": {"600036": "801050.SI"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bk = resolve_sector_bk("600036", "sh", cfg, root=tmp_path)
    assert bk == "801050.SI"
