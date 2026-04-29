#!/usr/bin/env python3
"""
批量修复 stock_name_cache.json：将所有「名称=代码」的失败条目写回正确简称。

优先「一次性」拉全市场 A 股列表（ak.stock_zh_a_spot_em 一次），再对未命中的代码单独查东财个股。

用法：
  python fix_stock_name_cache.py
  python fix_stock_name_cache.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_FILE = ROOT / "stock_name_cache.json"


def _build_spot_code_name_map() -> dict[str, str]:
    """一次请求拉全表，代码六位字符串 -> 名称。"""
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    codes = df["代码"].astype(str).str.strip().str.zfill(6)
    names = df["名称"].astype(str).str.strip()
    return dict(zip(codes, names))


def _fetch_name_em_only(code: str) -> str:
    """仅东财个股信息，用于全表未命中时的兜底。"""
    c = str(code).strip()
    if not c:
        return c
    try:
        import akshare as ak

        info = ak.stock_individual_info_em(symbol=c)
        name = str(info.loc[info["item"] == "股票简称", "value"].values[0])
        time.sleep(0.2)
        return name
    except Exception:
        return c


def main() -> int:
    ap = argparse.ArgumentParser(description="一次性批量修复「名称=代码」缓存")
    ap.add_argument("--dry-run", action="store_true", help="只列出待修复代码")
    args = ap.parse_args()

    if not CACHE_FILE.exists():
        print(f"未找到缓存文件：{CACHE_FILE}")
        return 1

    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读取失败：{e}")
        return 1
    if not isinstance(raw, dict):
        print("缓存格式不是 JSON 对象")
        return 1

    cache: dict[str, str] = {str(k): str(v) for k, v in raw.items()}
    to_fix = [k for k, v in cache.items() if str(k).strip() == str(v).strip()]

    if not to_fix:
        print("无需修复：没有「名称与代码相同」的条目。")
        return 0

    to_fix.sort()
    preview = ", ".join(to_fix[:25])
    print(f"待修复 {len(to_fix)} 条（示例）: {preview}{' …' if len(to_fix) > 25 else ''}")

    if args.dry_run:
        return 0

    print("正在一次性拉取全市场 A 股实时列表（仅 1 次网络请求）…")
    try:
        spot = _build_spot_code_name_map()
    except Exception as e:
        print(f"全市场表拉取失败，将逐只走东财个股接口：{e}")
        spot = {}

    fixed_batch = 0
    still: list[str] = []
    for code in to_fix:
        c6 = str(code).strip().zfill(6)
        name = spot.get(c6)
        if name and name != code:
            cache[code] = name
            fixed_batch += 1
        else:
            still.append(code)

    print(f"全表命中 {fixed_batch}/{len(to_fix)}，剩余 {len(still)} 条单独查询…")

    fixed_em = 0
    for i, code in enumerate(still, 1):
        cache.pop(code, None)
        n = _fetch_name_em_only(code)
        cache[code] = n
        if n != code:
            fixed_em += 1
            print(f"  [{i}/{len(still)}] {code} -> {n}")
        else:
            print(f"  [{i}/{len(still)}] {code} 仍无法解析（暂保留为代码）")

    try:
        CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"写入失败：{e}")
        return 1

    total_ok = fixed_batch + fixed_em
    print(
        f"完成：全表 {fixed_batch} 条 + 单独 {fixed_em} 条，共写入简称 {total_ok}/{len(to_fix)}，"
        f"已保存 {CACHE_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
