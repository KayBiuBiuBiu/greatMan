"""合并后的 config 与 config_schema.json 做 JSON Schema 校验（P2-2）。

Schema 设计说明见 config_schema.json 顶层 $comment（与 merge_full_config 同步维护）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).resolve().parent / "config_schema.json"
_schema: dict[str, Any] | None = None


def _load_schema() -> dict[str, Any]:
    global _schema
    if _schema is None:
        if not _SCHEMA_PATH.is_file():
            print(f"[config] 缺少 Schema 文件: {_SCHEMA_PATH}", file=sys.stderr)
            raise SystemExit(1)
        _schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema


def validate_merged_config(cfg: dict[str, Any]) -> None:
    """对 merge_full_config 的结果做校验；失败抛出 jsonschema.ValidationError。"""
    import jsonschema

    jsonschema.validate(instance=cfg, schema=_load_schema())


def validate_merged_config_or_exit(cfg: dict[str, Any]) -> None:
    """校验失败时打印路径与原因，sys.exit(1)。"""
    import jsonschema

    try:
        validate_merged_config(cfg)
    except jsonschema.ValidationError as e:
        parts = [str(x) for x in e.absolute_path]
        loc = " / ".join(parts) if parts else "(root)"
        print("[config] JSON Schema 校验失败，请检查 config.json：", file=sys.stderr)
        print(f"  路径: {loc}", file=sys.stderr)
        print(f"  原因: {e.message}", file=sys.stderr)
        raise SystemExit(1) from e
