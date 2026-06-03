"""参数锁定策略系统。

功能：
1. 参数锁定 - 指定哪些参数不自动调整
2. 变更冷却期 - 同一参数的变更间隔
3. 日/周变更限制 - 防止过度调整
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ParamLockPolicy:
    """参数锁定策略。"""

    def __init__(self, config_path: Path):
        """初始化锁定策略。

        Args:
            config_path: config.json 路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.change_log_file = self.config_path.parent / "data" / "param_change_log.jsonl"

    def _load_config(self) -> dict[str, Any]:
        """加载配置。"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return {}

    def is_param_locked(self, param_path: str) -> bool:
        """检查参数是否被锁定。

        Args:
            param_path: 参数路径，如 "drawdown_alert.warn_1_ratio"

        Returns:
            是否被锁定
        """
        lock_cfg = self.config.get("ops_automation", {}).get("param_lock_policy", {})
        locked_params = lock_cfg.get("locked_params", [])

        return param_path in locked_params

    def check_cooldown_violation(
        self,
        param_path: str,
        cooldown_hours: Optional[int] = None,
    ) -> bool:
        """检查参数是否在冷却期内。

        Args:
            param_path: 参数路径
            cooldown_hours: 冷却时间（小时），如果为 None 则从配置读取

        Returns:
            是否违反冷却期
        """
        if cooldown_hours is None:
            lock_cfg = self.config.get("ops_automation", {}).get("param_lock_policy", {})
            cooldown_hours = lock_cfg.get("cooldown_hours", 24)

        # 读取最后一次变更时间
        last_change_time = self._get_last_change_time(param_path)
        if last_change_time is None:
            return False

        # 检查是否在冷却期内
        elapsed_hours = (datetime.now() - last_change_time).total_seconds() / 3600
        return elapsed_hours < cooldown_hours

    def check_daily_change_limit(self) -> bool:
        """检查每日变更限制。

        Returns:
            是否超过每日限制
        """
        lock_cfg = self.config.get("ops_automation", {}).get("param_lock_policy", {})
        max_daily = lock_cfg.get("max_daily_changes", 5)

        # 统计今日变更数
        today_changes = self._count_changes_today()
        return today_changes >= max_daily

    def check_weekly_change_limit(self) -> bool:
        """检查每周变更限制。

        Returns:
            是否超过每周限制
        """
        lock_cfg = self.config.get("ops_automation", {}).get("param_lock_policy", {})
        max_weekly = lock_cfg.get("max_weekly_changes", 15)

        # 统计本周变更数
        week_changes = self._count_changes_this_week()
        return week_changes >= max_weekly

    def can_apply_changes(
        self,
        changes: list[dict[str, Any]],
    ) -> tuple[bool, list[str]]:
        """检查是否可以应用参数变更。

        Args:
            changes: 参数变更列表

        Returns:
            (can_apply, reasons)
        """
        reasons = []

        # 检查锁定的参数
        for change in changes:
            param_path = change.get('param_path', '')
            if self.is_param_locked(param_path):
                reasons.append(f"参数被锁定: {param_path}")

        # 检查冷却期
        for change in changes:
            param_path = change.get('param_path', '')
            if self.check_cooldown_violation(param_path):
                reasons.append(f"参数在冷却期内: {param_path}")

        # 检查每日限制
        if self.check_daily_change_limit():
            reasons.append("已达到每日变更限制")

        # 检查每周限制
        if self.check_weekly_change_limit():
            reasons.append("已达到每周变更限制")

        return len(reasons) == 0, reasons

    def _get_last_change_time(self, param_path: str) -> Optional[datetime]:
        """获取参数上次变更时间。"""
        try:
            if not self.change_log_file.exists():
                return None

            last_time = None
            with open(self.change_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    record = json.loads(line)
                    if record.get('param_path') == param_path:
                        last_time = datetime.fromisoformat(record['timestamp'])

            return last_time
        except Exception as e:
            logger.warning(f"读取变更历史失败: {e}")
            return None

    def _count_changes_today(self) -> int:
        """统计今日变更数。"""
        try:
            if not self.change_log_file.exists():
                return 0

            today = datetime.now().date()
            count = 0

            with open(self.change_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    record = json.loads(line)
                    change_date = datetime.fromisoformat(record['timestamp']).date()
                    if change_date == today:
                        count += 1

            return count
        except Exception e:
            logger.warning(f"统计每日变更失败: {e}")
            return 0

    def _count_changes_this_week(self) -> int:
        """统计本周变更数。"""
        try:
            if not self.change_log_file.exists():
                return 0

            week_start = datetime.now() - timedelta(days=datetime.now().weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
            count = 0

            with open(self.change_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    record = json.loads(line)
                    change_time = datetime.fromisoformat(record['timestamp'])
                    if change_time >= week_start:
                        count += 1

            return count
        except Exception as e:
            logger.warning(f"统计每周变更失败: {e}")
            return 0

    def log_change(self, param_path: str, old_value: Any, new_value: Any) -> None:
        """记录参数变更。"""
        try:
            self.change_log_file.parent.mkdir(parents=True, exist_ok=True)

            record = {
                'timestamp': datetime.now().isoformat(),
                'param_path': param_path,
                'old_value': old_value,
                'new_value': new_value,
            }

            with open(self.change_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        except Exception as e:
            logger.warning(f"记录参数变更失败: {e}")
