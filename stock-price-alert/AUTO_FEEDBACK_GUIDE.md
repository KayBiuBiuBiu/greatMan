# 自动反馈循环完整实现指南

## 🎉 功能概述

选股系统已完成**生产级的自动参数反馈循环**实现。包括：

### ✅ 已实现的核心功能

1. **参数版本管理** ✅
   - 自动创建版本快照
   - 完整审计日志
   - 一键回滚

2. **Config 热加载** ✅
   - 无需重启应用新参数
   - 自动文件监听

3. **邮件审批流程** ✅
   - HTML 格式审批邮件
   - 一键确认/拒绝链接
   - 审批历史记录

4. **自动回滚监控** ✅
   - 性能异常检测
   - 三级回滚规则
   - 自动执行回滚

5. **参数锁定策略** ✅
   - 防止过度调整
   - 冷却期控制
   - 每日/周变更限制

6. **Web 仪表板** ✅
   - 版本历史展示
   - 性能实时监控
   - 快速操作界面

---

## 🚀 快速开始

### 1. 查看参数版本历史

```bash
python3 param_rollback.py --list
```

### 2. 快速回滚到上一个版本

```bash
python3 param_rollback.py --to-previous
```

### 3. 回滚到指定版本

```bash
python3 param_rollback.py --to-version v20260603_150000
```

### 4. 启动 Web 仪表板

```bash
# 需先安装 Flask
pip install flask

# 启动服务器
python3 dashboard_server.py -c config.json --port 5000

# 访问浏览器
# http://localhost:5000/dashboard
```

---

## ⚙️ 配置说明

在 `config.json` 中配置自动反馈循环：

```json
{
  "ops_automation": {
    "auto_tune_apply": "auto",  // false|manual|auto
    
    "auto_feedback": {
      "enabled": true,
      "min_improvement_pct": 5.0,
      "min_sample_count": 10
    },
    
    "auto_rollback": {
      "enabled": true,
      "high_threshold_pct": 10.0,   // ≥10% 下降立即回滚
      "medium_threshold_pct": 5.0,  // 5-10% 邮件确认
      "check_hours": 24              // 检查周期（小时）
    },
    
    "param_lock_policy": {
      "locked_params": [
        "risk_control.position_size"  // 不自动调整的参数
      ],
      "cooldown_hours": 24,           // 参数变更间隔
      "max_daily_changes": 5,         // 每日最多变更数
      "max_weekly_changes": 15        // 每周最多变更数
    },
    
    "approval_mail": {
      "enabled": true,
      "approval_timeout_hours": 8,    // 审批超时时间
      "default_decision": "apply"     // 超时后的默认决策
    },
    
    "dashboard": {
      "enabled": true,
      "port": 5000,
      "bind": "127.0.0.1"
    }
  }
}
```

---

## 📊 完整工作流

### 早上 08:30
```
启动 run_alert.py
  ↓
热加载最新的 config.json（包含昨天的优化参数）
  ↓
使用新参数进行选股和实时监控
```

### 盘中 09:30-15:00
```
实时监控股价变动
  ↓
根据信号发出买卖建议
  ↓
记录交易结果
```

### 盘后 15:10
```
1. 回测性能评估
   ↓
2. 生成每日总结
   ↓
3. 运行参数优化 (auto_tune_accuracy.py)
   ↓
4. 检查参数锁定和冷却期
   ↓
5. 生成审批邮件
   ↓
6. 邮件发送 + 等待审批（或超时自动决策）
   ↓
7. 处理审批决策
   ↓
8. 应用参数到 config.json
   ↓
9. 启动自动回滚监控（24h 监听性能）
   ↓
10. 发送完成通知
```

### 第二天 08:30
```
新一轮循环开始，使用最新优化的参数
```

---

## 🔍 三种运行模式

### 模式 1: 手动审批（推荐用于新用户）

```json
{
  "ops_automation": {
    "auto_tune_apply": "manual"
  }
}
```

**流程**：
1. 自动调参完成 → 生成邮件
2. 人工审批（点击邮件链接）
3. 审批通过 → 自动应用参数

### 模式 2: 完全自动（生产环境）

```json
{
  "ops_automation": {
    "auto_tune_apply": "auto"
  }
}
```

**流程**：
1. 自动调参 → 性能验证
2. 自动应用（如果改进显著）
3. 启动回滚监控

### 模式 3: 仅 Dry-run（保守策略）

```json
{
  "ops_automation": {
    "auto_tune_apply": false
  }
}
```

**流程**：
1. 自动调参 → 生成建议
2. 不自动应用
3. 手动审查和决定

---

## 📧 邮件审批说明

参数优化完成后，你会收到类似这样的邮件：

```
📊 参数自动优化审批

版本号: v20260603_150000
生成时间: 2026-06-03 15:30:00
审批截止: 8 小时内

📈 性能指标对比
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

## 🛡️ 自动回滚规则

当新参数应用后 24 小时内，系统会监控性能变化：

### 级别 1: HIGH（命中率 ↓≥10%）
- **立即回滚**
- 发送告警邮件

### 级别 2: MEDIUM（命中率 ↓5-10%）
- **邮件确认后回滚**
- 待用户确认

### 级别 3: LOW（命中率 ↓<5%）
- **继续观察**
- 记录到日志

---

## 🔒 参数锁定示例

某些参数你可能希望保持稳定，不自动调整：

```json
{
  "param_lock_policy": {
    "locked_params": [
      "risk_control.position_size",    // 不自动调整仓位
      "drawdown_alert.warn_1_ratio"    // 不自动调整回撤警告
    ],
    "cooldown_hours": 24,               // 同一参数 24h 内不重复变更
    "max_daily_changes": 5,             // 每天最多变更 5 个参数
    "max_weekly_changes": 15            // 每周最多变更 15 个参数
  }
}
```

---

## 📊 仪表板功能

访问 `http://localhost:5000/dashboard` 可以：

### 1. 实时性能监控
- 今日盈利
- 买入/卖出数量
- 持仓信息

### 2. 版本历史管理
- 查看所有参数版本
- 版本的变更内容
- 一键回滚到任意版本

### 3. 快速操作
- 刷新数据
- 查看审批记录

### 4. 性能曲线（可扩展）
- 显示每个版本应用后的性能
- 对标历史基线

---

## 🔧 常见操作

### 查看某个版本的详细变更

```bash
cat data/config_versions/v20260603_150000.json
```

### 查看完整的审计日志

```bash
cat data/config_changes.log
```

### 查看审批历史

```bash
cat data/approval_history.json | python3 -m json.tool
```

### 查看性能异常记录

```bash
cat data/anomaly_records.jsonl | python3 -m json.tool
```

### 查看参数变更历史

```bash
cat data/param_change_log.jsonl | python3 -m json.tool
```

---

## ⚠️ 注意事项

1. **邮件配置**
   - 邮件审批需要配置邮件发送（使用已有的 notification 系统）
   - 或使用 Flask 仪表板中的 Web 确认链接

2. **Flask 仪表板**
   - 仅用于开发/测试，不建议直接暴露到外网
   - 生产环境应配置反向代理（nginx）和认证

3. **性能监控**
   - 需要在 `daily_summary.json` 中有性能数据才能触发回滚
   - 确保 `backtest_alerts` 运行正常

4. **参数版本**
   - 默认保留 30 天内的版本，更早的版本自动清理
   - 可修改 `cleanup_old_versions()` 的参数改变保留时间

---

## 🎯 成功标准检查清单

- ✅ 可以查看参数版本历史: `python3 param_rollback.py --list`
- ✅ 可以快速回滚: `python3 param_rollback.py --to-previous`
- ✅ 邮件审批生成: 收到审批邮件并成功确认/拒绝
- ✅ 自动回滚检测: 性能异常时自动触发回滚告警
- ✅ 参数锁定生效: 被锁定的参数不被调整
- ✅ 仪表板可用: `http://localhost:5000/dashboard` 正常显示
- ✅ 热加载生效: 修改 config.json 后无需重启 run_alert.py

---

## 🚨 故障排查

### 问题 1: 邮件没有发送
- 检查 config.json 中的邮件配置
- 检查网络连接
- 查看日志: `tail -f logs/run_alert.jsonl`

### 问题 2: 参数没有应用
- 检查 `auto_tune_apply` 配置
- 查看 `data/config_changes.log` 中的错误信息
- 确认参数未被锁定

### 问题 3: 自动回滚没有触发
- 检查 `auto_rollback.enabled` 是否为 true
- 检查 `daily_summary.json` 是否有性能数据
- 查看 `data/anomaly_records.jsonl`

### 问题 4: 仪表板无法访问
- 确保已安装 Flask: `pip install flask`
- 检查端口是否被占用: `lsof -i :5000`
- 查看服务器日志

---

## 📚 相关文件

- **核心组件**
  - `config_version_manager.py` - 版本管理
  - `param_rollback.py` - CLI 回滚工具
  - `feedback_executor.py` - 反馈执行器

- **扩展组件**
  - `param_approval_mail.py` - 邮件审批
  - `auto_rollback_monitor.py` - 回滚监控
  - `param_lock_policy.py` - 参数锁定
  - `dashboard_server.py` - Web 仪表板

- **数据文件**
  - `data/config_versions/` - 版本快照
  - `data/config_changes.log` - 审计日志
  - `data/approval_history.json` - 审批历史
  - `data/param_change_log.jsonl` - 变更历史
  - `data/anomaly_records.jsonl` - 异常记录

---

## 🎓 学习资源

1. **查看版本管理的工作原理**
   ```bash
   python3 -c "from config_version_manager import ConfigVersionManager; vm = ConfigVersionManager(Path('config.json')); print(vm.list_versions())"
   ```

2. **测试邮件生成**
   ```bash
   python3 -c "from param_approval_mail import ParamApprovalMail; mail = ParamApprovalMail(Path('config.json')); ..."
   ```

3. **监听性能异常**
   ```bash
   python3 -c "from auto_rollback_monitor import AutoRollbackMonitor; monitor = AutoRollbackMonitor(Path('config.json')); ..."
   ```

---

## 🔗 下一步

1. **配置 ops_automation** - 在 config.json 中设置自动反馈参数
2. **测试邮件系统** - 确保审批邮件能正常发送和接收
3. **启动仪表板** - 访问 Web 界面监控参数优化
4. **观察回滚规则** - 等待性能异常，验证自动回滚工作正常
5. **调整参数锁定** - 根据需求锁定某些参数

---

**实现完成！🎉 选股系统已形成完整的自动参数反馈闭环，支持邮件审批、自动回滚、参数锁定和 Web 仪表板。**
