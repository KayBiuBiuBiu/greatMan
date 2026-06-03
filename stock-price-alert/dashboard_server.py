#!/usr/bin/env python3
"""参数优化仪表板服务器。

提供 REST API 和 Web UI 用于查看参数版本、性能曲线、快速操作等。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 检查依赖
try:
    from flask import Flask, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


def create_dashboard_app(config_path: Path) -> Flask | None:
    """创建仪表板 Flask 应用。

    Args:
        config_path: config.json 路径

    Returns:
        Flask 应用或 None（如果 Flask 不可用）
    """
    if not FLASK_AVAILABLE:
        logger.warning("Flask 未安装，仪表板功能不可用")
        logger.warning("安装方法: pip install flask")
        return None

    app = Flask(__name__)
    config_dir = config_path.parent

    # ==================== API 端点 ====================

    @app.route('/api/versions', methods=['GET'])
    def get_versions_api() -> dict[str, Any]:
        """获取版本列表。"""
        try:
            from config_version_manager import ConfigVersionManager

            vm = ConfigVersionManager(config_path)
            limit = request.args.get('limit', default=20, type=int)
            history = vm.get_version_history(limit=limit)
            return jsonify(history)
        except Exception as e:
            logger.error(f"获取版本失败: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/version/<version_id>', methods=['GET'])
    def get_version_detail(version_id: str) -> dict[str, Any]:
        """获取版本详情。"""
        try:
            version_file = config_dir / "data" / "config_versions" / f"{version_id}.json"
            if not version_file.exists():
                return jsonify({"error": "版本不存在"}), 404

            with open(version_file, 'r', encoding='utf-8') as f:
                version_data = json.load(f)

            return jsonify(version_data)
        except Exception as e:
            logger.error(f"获取版本详情失败: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/performance', methods=['GET'])
    def get_performance_api() -> dict[str, Any]:
        """获取性能数据。"""
        try:
            # 从 daily_summary.json 读取最新性能数据
            summary_file = config_dir / "data" / "daily_summary.json"
            if not summary_file.exists():
                return jsonify({"error": "无性能数据"}), 404

            with open(summary_file, 'r', encoding='utf-8') as f:
                summary = json.load(f)

            # 提取关键性能指标
            trades = summary.get('trades', {})
            performance = {
                'date': summary.get('date'),
                'realized_profit': trades.get('realized_profit', 0),
                'unrealized_profit': trades.get('unrealized_profit', 0),
                'net_profit': trades.get('net_profit', 0),
                'buy_count': len(trades.get('buys', [])),
                'sell_count': len(trades.get('sells', [])),
            }

            return jsonify(performance)
        except Exception as e:
            logger.error(f"获取性能数据失败: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rollback/<version_id>', methods=['POST'])
    def rollback_api(version_id: str) -> dict[str, Any]:
        """执行回滚。"""
        try:
            from config_version_manager import ConfigVersionManager

            vm = ConfigVersionManager(config_path)
            success, msg = vm.rollback_to_version(version_id)

            if success:
                return jsonify({"success": True, "message": msg})
            else:
                return jsonify({"success": False, "message": msg}), 400

        except Exception as e:
            logger.error(f"回滚失败: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/approve/<approval_id>', methods=['POST', 'GET'])
    def approve_api(approval_id: str) -> dict[str, Any]:
        """处理审批。"""
        try:
            from param_approval_mail import ParamApprovalMail

            mail = ParamApprovalMail(config_path)

            # GET: 从 URL 参数获取决策
            if request.method == 'GET':
                decision = request.args.get('decision', 'approve')
                reason = request.args.get('reason', '')
            # POST: 从 JSON 获取决策
            else:
                data = request.get_json() or {}
                decision = data.get('decision', 'approve')
                reason = data.get('reason', '')

            success, msg = mail.handle_approval_callback(
                approval_id,
                decision,
                reason,
            )

            if success:
                return jsonify({"success": True, "message": msg})
            else:
                return jsonify({"success": False, "message": msg}), 400

        except Exception as e:
            logger.error(f"审批处理失败: {e}")
            return jsonify({"error": str(e)}), 500

    # ==================== 前端页面 ====================

    @app.route('/dashboard', methods=['GET'])
    def dashboard() -> str:
        """仪表板主页。"""
        return get_dashboard_html()

    @app.route('/static/dashboard.css', methods=['GET'])
    def dashboard_css() -> str:
        """仪表板 CSS。"""
        return get_dashboard_css(), 200, {'Content-Type': 'text/css'}

    @app.route('/static/dashboard.js', methods=['GET'])
    def dashboard_js() -> str:
        """仪表板 JavaScript。"""
        return get_dashboard_js(), 200, {'Content-Type': 'application/javascript'}

    return app


def get_dashboard_html() -> str:
    """返回仪表板 HTML。"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>参数优化仪表板</title>
        <link rel="stylesheet" href="/static/dashboard.css">
    </head>
    <body>
        <div class="container">
            <header>
                <h1>📊 参数优化仪表板</h1>
                <p>实时监控参数版本、性能指标和自动回滚</p>
            </header>

            <div class="content">
                <div class="panel">
                    <h2>📈 性能监控</h2>
                    <div id="performance" class="metric-grid">
                        <div class="metric">
                            <span class="label">今日盈利</span>
                            <span class="value" id="profit">-</span>
                        </div>
                        <div class="metric">
                            <span class="label">买入数</span>
                            <span class="value" id="buys">-</span>
                        </div>
                        <div class="metric">
                            <span class="label">卖出数</span>
                            <span class="value" id="sells">-</span>
                        </div>
                    </div>
                </div>

                <div class="panel">
                    <h2>📚 版本历史</h2>
                    <div id="versions" class="version-list"></div>
                </div>

                <div class="panel">
                    <h2>⚙️ 快速操作</h2>
                    <button onclick="refreshData()">🔄 刷新数据</button>
                    <button onclick="showApprovals()">📧 查看审批</button>
                </div>
            </div>
        </div>

        <script src="/static/dashboard.js"></script>
    </body>
    </html>
    """


def get_dashboard_css() -> str:
    """返回仪表板 CSS。"""
    return """
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background-color: #f5f5f5;
        color: #333;
    }

    .container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
    }

    header {
        background-color: #0066cc;
        color: white;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 20px;
    }

    header h1 {
        font-size: 28px;
        margin-bottom: 5px;
    }

    header p {
        font-size: 14px;
        opacity: 0.9;
    }

    .content {
        display: grid;
        gap: 20px;
    }

    .panel {
        background-color: white;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .panel h2 {
        font-size: 18px;
        margin-bottom: 15px;
        border-bottom: 2px solid #0066cc;
        padding-bottom: 10px;
    }

    .metric-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
    }

    .metric {
        background-color: #f9f9f9;
        padding: 15px;
        border-radius: 5px;
        border-left: 4px solid #0066cc;
    }

    .metric .label {
        display: block;
        font-size: 12px;
        color: #666;
        margin-bottom: 5px;
    }

    .metric .value {
        display: block;
        font-size: 24px;
        font-weight: bold;
        color: #0066cc;
    }

    .version-list {
        max-height: 400px;
        overflow-y: auto;
    }

    .version-item {
        padding: 10px;
        border-bottom: 1px solid #eee;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .version-item:last-child {
        border-bottom: none;
    }

    .version-info {
        flex: 1;
    }

    .version-id {
        font-weight: bold;
        color: #0066cc;
    }

    .version-time {
        font-size: 12px;
        color: #999;
    }

    button {
        background-color: #0066cc;
        color: white;
        border: none;
        padding: 10px 20px;
        border-radius: 5px;
        cursor: pointer;
        margin-right: 10px;
        margin-bottom: 10px;
    }

    button:hover {
        background-color: #0052a3;
    }

    .error {
        color: #dc3545;
    }

    .success {
        color: #28a745;
    }
    """


def get_dashboard_js() -> str:
    """返回仪表板 JavaScript。"""
    return """
    async function loadVersions() {
        try {
            const response = await fetch('/api/versions');
            const versions = await response.json();

            const container = document.getElementById('versions');
            container.innerHTML = '';

            versions.forEach(v => {
                const item = document.createElement('div');
                item.className = 'version-item';
                item.innerHTML = `
                    <div class="version-info">
                        <div class="version-id">${v.version_id}</div>
                        <div class="version-time">${v.timestamp} | ${v.source} | ${v.change_count} 变更</div>
                    </div>
                    <button onclick="doRollback('${v.version_id}')">回滚</button>
                `;
                container.appendChild(item);
            });
        } catch (e) {
            console.error('加载版本失败:', e);
        }
    }

    async function loadPerformance() {
        try {
            const response = await fetch('/api/performance');
            const perf = await response.json();

            document.getElementById('profit').textContent = perf.net_profit?.toFixed(2) || '-';
            document.getElementById('buys').textContent = perf.buy_count || '-';
            document.getElementById('sells').textContent = perf.sell_count || '-';
        } catch (e) {
            console.error('加载性能数据失败:', e);
        }
    }

    async function doRollback(versionId) {
        if (!confirm(`确认回滚到版本 ${versionId}?`)) return;

        try {
            const response = await fetch(`/api/rollback/${versionId}`, {method: 'POST'});
            const result = await response.json();
            alert(result.message);
            refreshData();
        } catch (e) {
            console.error('回滚失败:', e);
            alert('回滚失败: ' + e);
        }
    }

    function refreshData() {
        loadPerformance();
        loadVersions();
    }

    function showApprovals() {
        alert('审批功能在网页版本中已集成到邮件系统');
    }

    // 页面加载时初始化
    document.addEventListener('DOMContentLoaded', refreshData);
    // 每 30 秒自动刷新
    setInterval(refreshData, 30000);
    """


def run_dashboard_server(
    config_path: Path,
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: bool = False,
) -> None:
    """运行仪表板服务器。

    Args:
        config_path: config.json 路径
        host: 监听地址
        port: 监听端口
        debug: 是否启用调试模式
    """
    app = create_dashboard_app(config_path)
    if app is None:
        logger.error("无法创建仪表板应用，Flask 可能未安装")
        return

    logger.info(f"🚀 仪表板服务器启动: http://{host}:{port}/dashboard")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="参数优化仪表板")
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path.cwd() / "config.json",
        help="config.json 路径",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="监听地址",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="监听端口",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式",
    )

    args = parser.parse_args()
    run_dashboard_server(args.config, args.host, args.port, args.debug)
