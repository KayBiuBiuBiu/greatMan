#!/usr/bin/env python3
"""
从「A股列表」类 Excel（深交所导出常见列：A股代码、A股简称）合并进 a_share_names.json。

默认与网页导出一致：https://www.szse.cn/market/product/stock/list/index.html
（也可下载 xlsx 后本地导入，无需爬页面）

用法：
  python import_xlsx_to_a_share_names.py ~/Downloads/A股列表.xlsx
  python import_xlsx_to_a_share_names.py --dry-run ~/Downloads/A股列表.xlsx
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "a_share_names.json"


def _norm_code(v: object) -> str | None:
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{1,6}", s):
        return s.zfill(6)
    return None


def _norm_name(v: object) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    return s


def load_existing() -> dict[str, str]:
    if not OUT.exists():
        return {}
    try:
        raw = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        ks = str(k).strip()
        if len(ks) == 6 and ks.isdigit():
            out[ks] = str(v).strip()
    return out


def read_xlsx(path: Path) -> dict[str, str]:
    import pandas as pd

    df = pd.read_excel(path, dtype=object)
    cols = {str(c).strip(): c for c in df.columns}
    code_col = None
    name_col = None
    for key in ("A股代码", "代码", "证券代码"):
        if key in cols:
            code_col = cols[key]
            break
    for key in ("A股简称", "证券简称", "简称"):
        if key in cols:
            name_col = cols[key]
            break
    if code_col is None or name_col is None:
        raise SystemExit(
            f"未找到列 A股代码/A股简称（或 代码/简称）。实际列：{list(df.columns)}"
        )

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        c = _norm_code(row.get(code_col))
        n = _norm_name(row.get(name_col))
        if c and n:
            mapping[c] = n
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser(description="Excel A股列表 → 合并到 a_share_names.json")
    ap.add_argument(
        "xlsx",
        type=Path,
        nargs="?",
        default=Path.home() / "Downloads" / "A股列表.xlsx",
        help="xlsx 路径（默认 ~/Downloads/A股列表.xlsx）",
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = ap.parse_args()
    path = args.xlsx.expanduser().resolve()
    if not path.is_file():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1

    try:
        from_excel = read_xlsx(path)
    except ImportError:
        print("请先安装：pip install pandas openpyxl", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 1

    before = load_existing()
    merged = dict(before)
    overlap = sum(1 for k in from_excel if k in before)
    merged.update(from_excel)

    meta = {
        "_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_count": len(merged),
        "_source": f"xlsx:{path.name}",
        "_import_rows": len(from_excel),
        "_overlap_with_previous": overlap,
    }
    payload = {**meta, **merged}

    print(
        f"Excel 有效行：{len(from_excel)} | 合并前本地条数：{len(before)} | "
        f"与本地重叠代码：{overlap} | 合并后总条数：{len(merged)}"
    )

    if args.dry_run:
        return 0

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT}")
    print("提示：run_alert 会优先读 a_share_names.json；若进程已开，重启监控以重新加载本地表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
