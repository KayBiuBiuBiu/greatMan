"""参数版本管理和审计日志系统。

功能：
1. 参数版本控制 - 每次参数变更创建版本快照
2. 审计日志 - 记录所有参数变更
3. 原子性写入 - 保证配置文件完整性
4. 快速回滚 - 支持回滚到历史版本
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParameterChange:
    """参数变更记录。"""
    param_path: str          # 参数路径，如 "drawdown_alert.warn_1_ratio"
    old_value: Any           # 旧值
    new_value: Any           # 新值
    reason: str = ""         # 变更原因
    performance_metric: Optional[str] = None  # 性能指标，如 "hit_rate: 65% → 72%"


@dataclass
class ConfigVersion:
    """配置版本记录。"""
    version_id: str          # 版本号，格式: v20260603_150000
    timestamp: str           # ISO 时间戳
    source: str              # 变更来源: auto_tune|manual|rollback
    changes: list[ParameterChange] = field(default_factory=list)  # 变更列表
    reason: str = ""         # 总体变更原因
    config_snapshot: dict[str, Any] = field(default_factory=dict)  # config 快照

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（便于 JSON 序列化）。"""
        d = asdict(self)
        d['changes'] = [asdict(c) for c in self.changes]
        return d


class ConfigVersionManager:
    """参数版本管理器。"""

    def __init__(self, config_path: Path, versions_dir: Optional[Path] = None):
        """初始化版本管理器。

        Args:
            config_path: config.json 的路径
            versions_dir: 版本文件存储目录（默认: data/config_versions/）
        """
        self.config_path = Path(config_path)
        self.versions_dir = Path(versions_dir) if versions_dir else self.config_path.parent / "data" / "config_versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

        self.audit_log_path = self.config_path.parent / "data" / "config_changes.log"
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

        # 备份目录（旧逻辑兼容）
        self.backup_dir = self.config_path.parent / "data" / "config_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def apply_parameter_changes(
        self,
        changes: list[ParameterChange],
        reason: str = "",
        source: str = "manual",
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """应用参数变更。

        Args:
            changes: 参数变更列表
            reason: 变更原因
            source: 变更来源（auto_tune/manual/rollback）
            dry_run: 仅验证，不实际写入

        Returns:
            (success, message)
        """
        try:
            # 加载当前配置
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 创建配置副本用于变更
            new_config = copy.deepcopy(config)

            # 应用所有变更
            for change in changes:
                keys = change.param_path.split('.')
                target = new_config

                # 导航到参数路径
                for key in keys[:-1]:
                    if key not in target:
                        target[key] = {}
                    target = target[key]

                # 应用变更
                target[keys[-1]] = change.new_value

            # 验证 schema（如果存在）
            schema_path = self.config_path.parent / "config_schema.json"
            if schema_path.exists():
                try:
                    import jsonschema
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        schema = json.load(f)
                    jsonschema.validate(instance=new_config, schema=schema)
                except ImportError:
                    logger.warning("jsonschema 未安装，跳过 schema 验证")
                except jsonschema.ValidationError as e:
                    return False, f"Schema 验证失败: {e.message}"

            if dry_run:
                return True, "✓ Dry-run 验证通过（未写入）"

            # 创建版本记录
            version_id = datetime.now().strftime("v%Y%m%d_%H%M%S")
            version = ConfigVersion(
                version_id=version_id,
                timestamp=datetime.now().isoformat(),
                source=source,
                changes=changes,
                reason=reason,
                config_snapshot=new_config,
            )

            # 原子性写入新配置
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.json',
                dir=self.config_path.parent,
                delete=False,
                encoding='utf-8'
            ) as tmp:
                json.dump(new_config, tmp, ensure_ascii=False, indent=2)
                tmp_path = tmp.name

            try:
                # 备份旧配置
                backup_path = self.backup_dir / f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
                shutil.copy2(self.config_path, backup_path)

                # 用原子操作替换
                shutil.move(tmp_path, self.config_path)

                # 保存版本快照
                version_file = self.versions_dir / f"{version_id}.json"
                with open(version_file, 'w', encoding='utf-8') as f:
                    json.dump(version.to_dict(), f, ensure_ascii=False, indent=2)

                # 记录审计日志
                self._log_audit(version)

                msg = f"✓ 参数已应用 (版本: {version_id})"
                logger.info(msg)
                return True, msg

            except Exception as e:
                # 清理临时文件
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        except Exception as e:
            msg = f"✗ 参数应用失败: {e}"
            logger.error(msg)
            return False, msg

    def rollback_to_version(self, version_id: str) -> tuple[bool, str]:
        """回滚到指定版本。

        Args:
            version_id: 版本号，如 "v20260603_150000"

        Returns:
            (success, message)
        """
        try:
            version_file = self.versions_dir / f"{version_id}.json"
            if not version_file.exists():
                return False, f"✗ 版本不存在: {version_id}"

            # 加载版本配置
            with open(version_file, 'r', encoding='utf-8') as f:
                version_data = json.load(f)

            # 提取快照
            config_snapshot = version_data.get('config_snapshot', {})
            if not config_snapshot:
                return False, f"✗ 版本快照为空: {version_id}"

            # 原子性写入
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.json',
                dir=self.config_path.parent,
                delete=False,
                encoding='utf-8'
            ) as tmp:
                json.dump(config_snapshot, tmp, ensure_ascii=False, indent=2)
                tmp_path = tmp.name

            try:
                # 备份当前配置
                current_backup = self.backup_dir / f"config_before_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
                shutil.copy2(self.config_path, current_backup)

                # 用原子操作替换
                shutil.move(tmp_path, self.config_path)

                # 记录回滚审计日志
                self._log_audit_rollback(version_id)

                msg = f"✓ 已回滚到版本 {version_id}"
                logger.info(msg)
                return True, msg

            except Exception as e:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        except Exception as e:
            msg = f"✗ 回滚失败: {e}"
            logger.error(msg)
            return False, msg

    def get_version_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取版本历史（按时间倒序）。

        Args:
            limit: 返回的最大版本数

        Returns:
            版本信息列表
        """
        versions = []
        for version_file in sorted(self.versions_dir.glob("v*.json"), reverse=True)[:limit]:
            try:
                with open(version_file, 'r', encoding='utf-8') as f:
                    version_data = json.load(f)
                versions.append({
                    'version_id': version_data['version_id'],
                    'timestamp': version_data['timestamp'],
                    'source': version_data['source'],
                    'reason': version_data.get('reason', ''),
                    'change_count': len(version_data.get('changes', [])),
                })
            except Exception as e:
                logger.warning(f"读取版本文件失败 {version_file}: {e}")

        return versions

    def list_versions(self) -> str:
        """返回版本历史的格式化字符串。"""
        history = self.get_version_history(limit=20)
        if not history:
            return "📭 无版本历史"

        lines = ["📚 配置版本历史（最新 20 个）:\n"]
        for v in history:
            lines.append(
                f"  {v['version_id']} | {v['timestamp']}\n"
                f"    来源: {v['source']} | 变更数: {v['change_count']}\n"
                f"    原因: {v['reason']}\n"
            )
        return "".join(lines)

    def cleanup_old_versions(self, keep_days: int = 30) -> int:
        """清理超过指定天数的版本。

        Args:
            keep_days: 保留的天数

        Returns:
            删除的版本数
        """
        from datetime import timedelta

        cutoff_time = datetime.now() - timedelta(days=keep_days)
        deleted = 0

        for version_file in self.versions_dir.glob("v*.json"):
            try:
                with open(version_file, 'r', encoding='utf-8') as f:
                    version_data = json.load(f)

                version_time = datetime.fromisoformat(version_data['timestamp'])
                if version_time < cutoff_time:
                    version_file.unlink()
                    deleted += 1
                    logger.info(f"删除旧版本: {version_file.name}")
            except Exception as e:
                logger.warning(f"处理版本文件失败 {version_file}: {e}")

        return deleted

    def _log_audit(self, version: ConfigVersion) -> None:
        """记录审计日志。"""
        try:
            lines = [
                f"{'=' * 80}",
                f"时间: {version.timestamp}",
                f"版本: {version.version_id}",
                f"来源: {version.source}",
                f"原因: {version.reason}",
                f"变更数: {len(version.changes)}",
            ]

            for change in version.changes:
                lines.append(
                    f"  • {change.param_path}: {change.old_value} → {change.new_value}"
                )
                if change.reason:
                    lines.append(f"    理由: {change.reason}")
                if change.performance_metric:
                    lines.append(f"    指标: {change.performance_metric}")

            with open(self.audit_log_path, 'a', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n\n")

        except Exception as e:
            logger.error(f"审计日志记录失败: {e}")

    def _log_audit_rollback(self, version_id: str) -> None:
        """记录回滚审计日志。"""
        try:
            lines = [
                f"{'=' * 80}",
                f"时间: {datetime.now().isoformat()}",
                f"操作: 回滚到版本 {version_id}",
            ]

            with open(self.audit_log_path, 'a', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n\n")

        except Exception as e:
            logger.error(f"审计日志记录失败: {e}")
