#!/usr/bin/env python3
"""参数快速回滚工具。

用法：
  python3 param_rollback.py --list                    # 列出版本历史
  python3 param_rollback.py --to-previous             # 回滚到上一个版本
  python3 param_rollback.py --to-version v20260603_150000  # 回滚到指定版本
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config_version_manager import ConfigVersionManager


def main() -> int:
    """主函数。"""
    parser = argparse.ArgumentParser(
        description="参数快速回滚工具",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list",
        action="store_true",
        help="列出版本历史",
    )
    group.add_argument(
        "--to-previous",
        action="store_true",
        help="回滚到上一个版本",
    )
    group.add_argument(
        "--to-version",
        type=str,
        help="回滚到指定版本 (e.g., v20260603_150000)",
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path.cwd() / "config.json",
        help="config.json 路径 (默认: config.json)",
    )

    args = parser.parse_args()

    # 检查 config 文件
    if not args.config.exists():
        print(f"❌ 配置文件不存在: {args.config}")
        return 1

    vm = ConfigVersionManager(args.config)

    # --list: 列出版本历史
    if args.list:
        print(vm.list_versions())
        return 0

    # --to-previous: 回滚到上一个版本
    if args.to_previous:
        history = vm.get_version_history(limit=2)
        if len(history) < 2:
            print("❌ 版本历史数量不足（需要至少 2 个版本）")
            return 1

        prev_version = history[1]['version_id']
        print(f"回滚到上一个版本: {prev_version}")
        success, msg = vm.rollback_to_version(prev_version)
        print(msg)
        return 0 if success else 1

    # --to-version: 回滚到指定版本
    if args.to_version:
        print(f"回滚到版本: {args.to_version}")
        success, msg = vm.rollback_to_version(args.to_version)
        print(msg)
        return 0 if success else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
