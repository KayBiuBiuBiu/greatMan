"""参数优化邮件审批系统。

功能：
1. 生成审批邮件 - 参数变更、性能指标、风险评估
2. 审批记录 - 审批历史和决策
3. 邮件回调处理 - 接收确认/拒绝决策
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRecord:
    """审批记录。"""
    approval_id: str          # 唯一审批 ID
    version_id: str           # 对应的参数版本
    timestamp: str            # 审批时间
    changes: list[dict[str, Any]]  # 参数变更列表
    performance_metrics: dict[str, Any]  # 性能指标
    status: str = "pending"   # pending|approved|rejected|expired
    decision_time: Optional[str] = None  # 决策时间
    decision_reason: str = ""  # 决策原因
    approval_link: str = ""   # 审批链接


class ParamApprovalMail:
    """参数审批邮件系统。"""

    def __init__(self, config_path: Path):
        """初始化审批系统。

        Args:
            config_path: config.json 路径
        """
        self.config_path = Path(config_path)
        self.approval_dir = self.config_path.parent / "data" / "approvals"
        self.approval_dir.mkdir(parents=True, exist_ok=True)
        self.approval_history_file = self.config_path.parent / "data" / "approval_history.json"

    def generate_approval_html(
        self,
        version_id: str,
        changes: list[dict[str, Any]],
        performance_metrics: dict[str, Any],
        approval_timeout_hours: int = 8,
    ) -> tuple[str, ApprovalRecord]:
        """生成审批邮件 HTML。

        Args:
            version_id: 参数版本号
            changes: 参数变更列表
            performance_metrics: 性能指标
            approval_timeout_hours: 审批超时时间

        Returns:
            (html_content, approval_record)
        """
        # 生成审批 ID
        approval_id = self._generate_approval_id(version_id)
        approval_link = f"http://localhost:5000/api/approve/{approval_id}"

        # 构建变更表格
        changes_html = self._build_changes_table(changes)

        # 构建性能指标表格
        metrics_html = self._build_metrics_table(performance_metrics)

        # 生成 HTML
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 微软雅黑, Arial, sans-serif; font-size: 12px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
                th {{ background-color: #f0f0f0; border: 1px solid #ddd; padding: 8px; text-align: left; }}
                td {{ border: 1px solid #ddd; padding: 8px; }}
                .header {{ background-color: #0066cc; color: white; padding: 20px; }}
                .action {{ margin: 20px 0; }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    margin: 5px;
                    border-radius: 5px;
                    text-decoration: none;
                    font-weight: bold;
                }}
                .approve {{ background-color: #28a745; color: white; }}
                .reject {{ background-color: #dc3545; color: white; }}
                .history {{ background-color: #17a2b8; color: white; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>📊 参数自动优化审批</h2>
            </div>

            <p><strong>版本号:</strong> {version_id}</p>
            <p><strong>生成时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>审批截止:</strong> {approval_timeout_hours} 小时内</p>

            <h3>📈 性能指标对比</h3>
            {metrics_html}

            <h3>🔧 参数变更</h3>
            {changes_html}

            <h3>✅ 快速操作</h3>
            <div class="action">
                <a href="{approval_link}?decision=approve" class="button approve">✓ 确认应用</a>
                <a href="{approval_link}?decision=reject" class="button reject">✗ 拒绝</a>
                <a href="http://localhost:5000/dashboard" class="button history">↺ 查看历史</a>
            </div>

            <hr>
            <p style="color: #666; font-size: 11px;">
            自动优化系统 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 本邮件无需回复
            </p>
        </body>
        </html>
        """

        # 创建审批记录
        record = ApprovalRecord(
            approval_id=approval_id,
            version_id=version_id,
            timestamp=datetime.now().isoformat(),
            changes=changes,
            performance_metrics=performance_metrics,
            approval_link=approval_link,
        )

        # 保存审批记录
        self._save_approval_record(record)

        return html, record

    def handle_approval_callback(
        self,
        approval_id: str,
        decision: str,
        reason: str = "",
    ) -> tuple[bool, str]:
        """处理审批回调。

        Args:
            approval_id: 审批 ID
            decision: approve|reject
            reason: 决策原因

        Returns:
            (success, message)
        """
        try:
            record = self._load_approval_record(approval_id)
            if not record:
                return False, f"审批记录不存在: {approval_id}"

            if record.status != "pending":
                return False, f"审批已结束: {record.status}"

            # 更新审批状态
            record.status = "approved" if decision == "approve" else "rejected"
            record.decision_time = datetime.now().isoformat()
            record.decision_reason = reason

            # 保存更新
            self._save_approval_record(record)

            # 记录到历史
            self._log_approval(record)

            msg = f"✓ 审批已{'通过' if decision == 'approve' else '拒绝'}: {approval_id}"
            logger.info(msg)
            return True, msg

        except Exception as e:
            msg = f"❌ 审批处理失败: {e}"
            logger.error(msg)
            return False, msg

    def check_approval_timeout(
        self,
        approval_id: str,
        timeout_hours: int = 8,
        default_decision: str = "apply",
    ) -> Optional[str]:
        """检查审批是否超时。

        Args:
            approval_id: 审批 ID
            timeout_hours: 超时时间（小时）
            default_decision: 超时后的默认决策（apply|reject）

        Returns:
            决策结果（如果超时）或 None
        """
        try:
            record = self._load_approval_record(approval_id)
            if not record or record.status != "pending":
                return None

            elapsed_seconds = time.time() - datetime.fromisoformat(record.timestamp).timestamp()
            timeout_seconds = timeout_hours * 3600

            if elapsed_seconds > timeout_seconds:
                # 超时，执行默认决策
                self.handle_approval_callback(
                    approval_id,
                    "approve" if default_decision == "apply" else "reject",
                    reason=f"审批超时 ({timeout_hours}h)，执行默认决策",
                )
                return default_decision

            return None

        except Exception as e:
            logger.warning(f"超时检查失败: {e}")
            return None

    def _build_changes_table(self, changes: list[dict[str, Any]]) -> str:
        """构建变更表格 HTML。"""
        rows = []
        for change in changes:
            rows.append(
                f"""
                <tr>
                  <td>{change.get('param_path', '')}</td>
                  <td><code>{change.get('old_value', '')}</code></td>
                  <td><code>{change.get('new_value', '')}</code></td>
                  <td>{change.get('reason', '')}</td>
                </tr>
                """
            )

        table = f"""
        <table>
        <tr style="background-color: #f0f0f0;">
          <th>参数</th>
          <th>旧值</th>
          <th>新值</th>
          <th>原因</th>
        </tr>
        {''.join(rows)}
        </table>
        """
        return table

    def _build_metrics_table(self, metrics: dict[str, Any]) -> str:
        """构建性能指标表格 HTML。"""
        rows = []
        for metric_name, metric_value in metrics.items():
            rows.append(
                f"""
                <tr>
                  <td><strong>{metric_name}</strong></td>
                  <td>{metric_value}</td>
                </tr>
                """
            )

        table = f"""
        <table>
        <tr style="background-color: #f0f0f0;">
          <th>指标</th>
          <th>数值</th>
        </tr>
        {''.join(rows)}
        </table>
        """
        return table

    def _generate_approval_id(self, version_id: str) -> str:
        """生成唯一的审批 ID。"""
        content = f"{version_id}_{datetime.now().isoformat()}".encode()
        return hashlib.md5(content).hexdigest()[:16]

    def _save_approval_record(self, record: ApprovalRecord) -> None:
        """保存审批记录。"""
        file_path = self.approval_dir / f"{record.approval_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            # 转换为字典以便 JSON 序列化
            record_dict = {
                'approval_id': record.approval_id,
                'version_id': record.version_id,
                'timestamp': record.timestamp,
                'changes': record.changes,
                'performance_metrics': record.performance_metrics,
                'status': record.status,
                'decision_time': record.decision_time,
                'decision_reason': record.decision_reason,
                'approval_link': record.approval_link,
            }
            json.dump(record_dict, f, ensure_ascii=False, indent=2)

    def _load_approval_record(self, approval_id: str) -> Optional[ApprovalRecord]:
        """加载审批记录。"""
        file_path = self.approval_dir / f"{approval_id}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return ApprovalRecord(
                approval_id=data['approval_id'],
                version_id=data['version_id'],
                timestamp=data['timestamp'],
                changes=data['changes'],
                performance_metrics=data['performance_metrics'],
                status=data['status'],
                decision_time=data.get('decision_time'),
                decision_reason=data.get('decision_reason', ''),
                approval_link=data.get('approval_link', ''),
            )
        except Exception as e:
            logger.warning(f"加载审批记录失败: {e}")
            return None

    def _log_approval(self, record: ApprovalRecord) -> None:
        """记录审批历史。"""
        try:
            # 加载历史记录
            history = []
            if self.approval_history_file.exists():
                with open(self.approval_history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)

            # 添加新记录
            history.append({
                'approval_id': record.approval_id,
                'version_id': record.version_id,
                'timestamp': record.timestamp,
                'status': record.status,
                'decision_time': record.decision_time,
                'decision_reason': record.decision_reason,
            })

            # 保存历史记录
            with open(self.approval_history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"审批历史记录失败: {e}")
