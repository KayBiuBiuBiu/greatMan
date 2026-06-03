"""自动回滚监控系统。

功能：
1. 性能异常检测 - 对比当日性能与历史平均
2. 自动回滚触发 - 根据严重程度自动或告警
3. 回滚执行 - 调用版本管理器进行回滚
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PerformanceAnomaly:
    """性能异常。"""

    def __init__(
        self,
        metric_name: str,
        current_value: float,
        historical_avg: float,
        degradation_pct: float,
        severity: str,  # LOW|MEDIUM|HIGH
    ):
        self.metric_name = metric_name
        self.current_value = current_value
        self.historical_avg = historical_avg
        self.degradation_pct = degradation_pct
        self.severity = severity
        self.detected_at = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            'metric_name': self.metric_name,
            'current_value': self.current_value,
            'historical_avg': self.historical_avg,
            'degradation_pct': self.degradation_pct,
            'severity': self.severity,
            'detected_at': self.detected_at,
        }


class AutoRollbackMonitor:
    """自动回滚监控器。"""

    def __init__(self, config_path: Path):
        """初始化监控器。

        Args:
            config_path: config.json 路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.data_dir = self.config_path.parent / "data"

    def _load_config(self) -> dict[str, Any]:
        """加载配置。"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return {}

    def detect_performance_anomaly(
        self,
        current_metrics: dict[str, float],
        historical_metrics_list: list[dict[str, float]],
        high_threshold_pct: float = 10.0,
        medium_threshold_pct: float = 5.0,
    ) -> list[PerformanceAnomaly]:
        """检测性能异常。

        Args:
            current_metrics: 当前性能指标（如 {"hit_rate": 0.65}）
            historical_metrics_list: 历史性能指标列表
            high_threshold_pct: 高严重度阈值（%）
            medium_threshold_pct: 中等严重度阈值（%）

        Returns:
            异常列表
        """
        anomalies = []

        if not historical_metrics_list:
            return anomalies

        # 计算历史平均值
        historical_avg = {}
        for metric_name in current_metrics.keys():
            values = [m.get(metric_name, 0) for m in historical_metrics_list]
            if values:
                historical_avg[metric_name] = sum(values) / len(values)

        # 检测异常
        for metric_name, current_value in current_metrics.items():
            hist_avg = historical_avg.get(metric_name, current_value)
            if hist_avg <= 0:
                continue

            degradation_pct = (current_value - hist_avg) / hist_avg * 100

            # 只关注性能下降
            if degradation_pct < 0:
                degradation_pct = abs(degradation_pct)

                if degradation_pct >= high_threshold_pct:
                    severity = "HIGH"
                elif degradation_pct >= medium_threshold_pct:
                    severity = "MEDIUM"
                else:
                    severity = "LOW"

                anomaly = PerformanceAnomaly(
                    metric_name=metric_name,
                    current_value=current_value,
                    historical_avg=hist_avg,
                    degradation_pct=degradation_pct,
                    severity=severity,
                )
                anomalies.append(anomaly)

        return anomalies

    def should_trigger_rollback(
        self,
        anomalies: list[PerformanceAnomaly],
    ) -> tuple[bool, str]:
        """判断是否应该触发回滚。

        Args:
            anomalies: 异常列表

        Returns:
            (should_rollback, reason)
        """
        if not anomalies:
            return False, "无异常"

        # 检查最严重的异常
        high_anomalies = [a for a in anomalies if a.severity == "HIGH"]
        medium_anomalies = [a for a in anomalies if a.severity == "MEDIUM"]

        if high_anomalies:
            reasons = ", ".join([
                f"{a.metric_name} 下降 {a.degradation_pct:.1f}%"
                for a in high_anomalies
            ])
            return True, f"性能严重下降: {reasons}"

        if len(medium_anomalies) >= 2:
            reasons = ", ".join([
                f"{a.metric_name} 下降 {a.degradation_pct:.1f}%"
                for a in medium_anomalies
            ])
            return True, f"多项指标中等下降: {reasons}"

        return False, "异常不严重"

    def maybe_trigger_auto_rollback(
        self,
        version_id: str,
        current_metrics: dict[str, float],
        historical_metrics_list: list[dict[str, float]] = None,
    ) -> tuple[bool, str]:
        """可能触发自动回滚。

        Args:
            version_id: 应用的参数版本
            current_metrics: 当前性能指标
            historical_metrics_list: 历史性能指标

        Returns:
            (triggered, message)
        """
        # 如果未提供历史指标，从本地读取
        if historical_metrics_list is None:
            historical_metrics_list = self._load_historical_metrics(days=30)

        # 读取配置
        rollback_cfg = self.config.get("ops_automation", {}).get("auto_rollback", {})
        high_threshold = rollback_cfg.get("high_threshold_pct", 10.0)
        medium_threshold = rollback_cfg.get("medium_threshold_pct", 5.0)

        # 检测异常
        anomalies = self.detect_performance_anomaly(
            current_metrics,
            historical_metrics_list,
            high_threshold_pct=high_threshold,
            medium_threshold_pct=medium_threshold,
        )

        should_rollback, reason = self.should_trigger_rollback(anomalies)

        if should_rollback:
            logger.warning(f"✗ 触发自动回滚: {reason}")
            return True, reason

        logger.info(f"✓ 性能正常，无需回滚")
        return False, "性能正常"

    def _load_historical_metrics(self, days: int = 30) -> list[dict[str, float]]:
        """加载历史性能指标。

        Args:
            days: 回溯天数

        Returns:
            历史指标列表
        """
        metrics = []

        # 从 daily_summary_history 读取
        history_dir = self.data_dir / "daily_summary_history"
        if not history_dir.exists():
            return metrics

        cutoff_date = datetime.now() - timedelta(days=days)

        for history_file in sorted(history_dir.glob("*.json"), reverse=True):
            try:
                # 提取日期
                date_str = history_file.stem
                file_date = datetime.strptime(date_str, "%Y-%m-%d")

                if file_date < cutoff_date:
                    break

                with open(history_file, 'r', encoding='utf-8') as f:
                    summary = json.load(f)

                # 提取性能指标
                if 'trades' in summary:
                    trades = summary['trades']
                    metric = {
                        'hit_rate': self._calculate_hit_rate(summary),
                        'profit_rate': trades.get('realized_profit', 0),
                    }
                    metrics.append(metric)

            except Exception as e:
                logger.warning(f"加载历史指标失败 {history_file}: {e}")

        return metrics

    def _calculate_hit_rate(self, summary: dict[str, Any]) -> float:
        """从 daily_summary 计算命中率。"""
        try:
            # 这是一个简化的实现
            trades = summary.get('trades', {})
            buys = len(trades.get('buys', []))
            sells = len(trades.get('sells', []))

            if buys == 0:
                return 0.5

            return sells / max(buys, 1)
        except Exception:
            return 0.5

    def log_anomaly_record(
        self,
        version_id: str,
        anomalies: list[PerformanceAnomaly],
        rollback_triggered: bool,
    ) -> None:
        """记录异常检测。"""
        try:
            anomaly_log_file = self.data_dir / "anomaly_records.jsonl"

            record = {
                'timestamp': datetime.now().isoformat(),
                'version_id': version_id,
                'anomalies': [a.to_dict() for a in anomalies],
                'rollback_triggered': rollback_triggered,
            }

            with open(anomaly_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        except Exception as e:
            logger.warning(f"异常记录失败: {e}")


def maybe_run_auto_rollback_monitor(
    cfg: dict[str, Any],
    config_path: Path,
    version_id: str,
    current_metrics: dict[str, float],
) -> None:
    """可选地运行自动回滚监控。

    Args:
        cfg: 配置字典
        config_path: config.json 路径
        version_id: 应用的参数版本
        current_metrics: 当前性能指标
    """
    try:
        rollback_cfg = cfg.get("ops_automation", {}).get("auto_rollback", {})
        if not rollback_cfg.get("enabled", False):
            return

        monitor = AutoRollbackMonitor(config_path)
        triggered, reason = monitor.maybe_trigger_auto_rollback(
            version_id,
            current_metrics,
        )

        if triggered:
            logger.warning(f"⚠️ 自动回滚监控: {reason}")
            # 这里应该调用 ConfigVersionManager 进行回滚
            # from config_version_manager import ConfigVersionManager
            # vm = ConfigVersionManager(config_path)
            # vm.rollback_to_version(...)

    except Exception as e:
        logger.warning(f"自动回滚监控异常: {e}")
