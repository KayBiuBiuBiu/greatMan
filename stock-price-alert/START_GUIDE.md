# 🚀 选股系统完全自动化启动指南

## ✨ 现在你可以这样运行系统

```bash
cd /Users/haha/greatMan/stock-price-alert
.venv/bin/python3 run_alert.py -c config.json --stdin-commands
```

**就这样！** 系统会自动处理一切。

---

## 📊 系统自动做什么

### ✅ 每天早上 08:30
```
启动 run_alert.py
  → 热加载最新 config.json（昨天自动优化的参数）
  → 使用新参数进行选股和实时监控
```

### ✅ 全天 09:30-15:00
```
实时监控股价
  → 发出买卖信号
  → 执行风险控制
  → 记录所有交易
```

### ✅ 每天盘后 15:10
```
性能回测（last 7 days）
  ↓
生成每日总结
  ↓
自动优化参数 (auto_tune_accuracy)
  ↓
检查参数锁定和冷却期
  ↓
生成审批邮件（如果有新参数）
  ↓
邮件发送 + 等待审批（8小时超时，或自动应用）
  ↓
应用参数到 config.json
  ↓
启动 24h 回滚监控
  ↓
发送完成通知
```

### ✅ 后续 24h 自动监控
```
监听性能指标
  → 性能正常（↓<5%）：继续使用
  → 性能中等下降（↓5-10%）：发邮件通知
  → 性能严重下降（↓≥10%）：自动回滚
```

### ✅ 第二天 08:30
```
循环继续，使用新优化的参数
```

---

## 🎯 初始配置（一次性）

编辑 `config.json`，在 `ops_automation` 部分添加：

```json
{
  "ops_automation": {
    "enabled": true,
    
    // 参数优化应用模式
    "auto_tune_apply": "auto",     // auto|manual|false
    
    // 邮件审批
    "approval_mail": {
      "enabled": true,
      "approval_timeout_hours": 8,    // 审批超时时间
      "default_decision": "apply"     // 超时后的默认决策
    },
    
    // 自动回滚
    "auto_rollback": {
      "enabled": true,
      "high_threshold_pct": 10.0,     // ≥10% 下降立即回滚
      "medium_threshold_pct": 5.0,    // 5-10% 邮件确认
      "check_hours": 24               // 监控周期
    },
    
    // 参数锁定
    "param_lock_policy": {
      "locked_params": [],            // 锁定的参数（不自动调整）
      "cooldown_hours": 24,           // 参数变更间隔
      "max_daily_changes": 5,         // 每天最多变更数
      "max_weekly_changes": 15        // 每周最多变更数
    },
    
    // 其他自动化
    "preopen_enabled": true,          // 开盘前同步K线
    "daily_summary_enabled": true,    // 生成每日总结
    "auto_tune_email": true           // 发邮件通知调参
  }
}
```

---

## 🎛️ 三种运行模式

### 模式 1: 完全自动（推荐生产）
```json
"auto_tune_apply": "auto"
```
参数优化 → 自动验证 → 自动应用 → 自动监控

### 模式 2: 手动审批（推荐新用户）
```json
"auto_tune_apply": "manual"
```
参数优化 → 邮件通知 → 人工确认 → 自动应用

### 模式 3: Dry-run（保守）
```json
"auto_tune_apply": false
```
参数优化 → 生成建议 → 不自动应用 → 手动审查

---

## 📈 可视化监控

### 启动 Web 仪表板
```bash
# 先安装 Flask（可选）
pip install flask

# 启动服务器
python3 dashboard_server.py -c config.json --port 5000

# 访问浏览器
# http://localhost:5000/dashboard
```

仪表板显示：
- 实时性能监控（今日盈利、买卖数）
- 参数版本历史
- 一键回滚功能

---

## 🔧 常用命令

### 查看版本历史
```bash
python3 param_rollback.py --list
```

### 手动回滚到上一个版本
```bash
python3 param_rollback.py --to-previous
```

### 回滚到指定版本
```bash
python3 param_rollback.py --to-version v20260603_150000
```

### 查看完整审计日志
```bash
cat data/config_changes.log
```

### 查看审批历史
```bash
cat data/approval_history.json | python3 -m json.tool
```

---

## 📧 邮件审批说明

当参数优化完成时，你会收到类似这样的邮件：

```
📊 参数自动优化审批

版本号: v20260603_150000
生成时间: 2026-06-03 15:30:00
审批截止: 8 小时内

📈 性能指标
┌─────────┬──────┐
│ 指标    │ 数值 │
├─────────┼──────┤
│ 命中率  │ 72%  │
│ 收益率  │ 2.3% │
└─────────┴──────┘

🔧 参数变更
┌──────────────┬────┬────┬────┐
│ 参数         │ 旧 │ 新 │ 原因 │
├──────────────┼────┼────┼────┤
│ warn_1_ratio │-0.06│-0.07│命中率偏高 │
└──────────────┴────┴────┴────┘

✅ 快速操作
[✓ 确认应用] [✗ 拒绝] [↺ 查看历史]
```

点击链接即可做出决策。8 小时后自动按默认策略处理。

---

## 🛡️ 自动回滚说明

新参数应用后，系统会在 24 小时内监控性能：

### ✓ 正常情况（命中率 ↓<5%）
```
继续使用新参数
  → 记录到日志
  → 下一轮参数优化时对标
```

### ⚠️ 中等下降（命中率 ↓5-10%）
```
发送告警邮件
  → 需人工确认
  → 确认后自动回滚
```

### 🔴 严重下降（命中率 ↓≥10%）
```
立即自动回滚
  → 恢复到上一个版本
  → 发送通知邮件
```

---

## 🔍 参数锁定示例

某些参数可能希望保持稳定，不自动调整：

```json
{
  "param_lock_policy": {
    "locked_params": [
      "risk_control.position_size",    // 不自动调整仓位
      "drawdown_alert.warn_1_ratio"    // 不自动调整回撤警告
    ],
    "cooldown_hours": 24,              // 同一参数 24h 内不重复变更
    "max_daily_changes": 5,            // 每天最多变更 5 个参数
    "max_weekly_changes": 15           // 每周最多变更 15 个参数
  }
}
```

---

## 📚 数据文件位置

所有自动化产生的数据都存储在 `data/` 目录：

```
data/
├── config_versions/              # 参数版本快照
│   ├── v20260603_150000.json
│   └── v20260603_160000.json
├── config_changes.log            # 审计日志（所有变更）
├── approval_history.json         # 审批历史
├── param_change_log.jsonl        # 参数变更历史
├── anomaly_records.jsonl         # 性能异常记录
└── approvals/                   # 审批记录文件
    ├── a1b2c3d4e5f6g7h8.json
    └── ...
```

---

## 🚨 故障排查

### 问题：邮件没有发送
- 检查 notification 配置
- 查看日志：`tail -f logs/run_alert.jsonl`
- 确保网络连接正常

### 问题：参数没有应用
- 检查 `auto_tune_apply` 配置
- 查看 `data/config_changes.log`
- 检查参数是否被锁定

### 问题：自动回滚没有触发
- 检查 `auto_rollback.enabled=true`
- 查看 `data/anomaly_records.jsonl`
- 确保 `daily_summary.json` 有性能数据

### 问题：仪表板无法访问
- 安装 Flask：`pip install flask`
- 检查端口是否被占用：`lsof -i :5000`
- 查看服务器日志

---

## ✨ 关键成就

✅ **完全自动化** - 无需人工干预日常运营
✅ **参数优化** - 自动调整策略参数
✅ **邮件审批** - 重要变更需人工确认（可选）
✅ **性能监控** - 24h 实时监控新参数效果
✅ **自动回滚** - 性能下降时智能回滚
✅ **参数锁定** - 防止过度调整
✅ **完整审计** - 所有操作都有记录
✅ **Web 仪表板** - 可视化管理

---

## 🎯 现在开始

```bash
# 1. 编辑配置
nano config.json
# 在 ops_automation 中启用新功能

# 2. 启动系统
.venv/bin/python3 run_alert.py -c config.json --stdin-commands

# 3. 可选：启动仪表板
# python3 dashboard_server.py -c config.json --port 5000
```

**就这样！系统会自动运行，每天不断优化参数，帮你赚钱。** 🚀

---

## 📞 帮助

- 完整文档：`AUTO_FEEDBACK_GUIDE.md`
- 参数版本：`python3 param_rollback.py --list`
- 仪表板：`http://localhost:5000/dashboard`

**祝好运！** 🍀
