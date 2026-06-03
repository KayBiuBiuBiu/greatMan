# 📊 自动参数优化配置说明

## 🎯 开启自动参数优化

编辑 `config.json`，找到 `ops_automation` 部分：

```json
{
  "ops_automation": {
    "enabled": true,
    "after_close_enabled": true,
    "param_optimization_enabled": false,  // ← 改为 true
    ...
  }
}
```

## ⏱️ 执行时机

- **何时运行**: 收盘后 (15:10 之后)
- **频率**: 每个工作日一次
- **耗时**: 5-10 分钟（快速分析模式）
- **依赖**: 必须先完成 `backtest_alerts` 和 `auto_tune`

## 📋 执行顺序

收盘后自动化任务流程：

```
1. backtest_alerts.py     (回测最近7天的alert)
2. daily_summary.py       (生成每日总结)
3. auto_tune_accuracy.py  (自动调参)
4. param_optimization_analysis.py  (← 参数优化，if enabled)
5. ml_nb_incremental.py   (ML模型增量训练，if enabled)
```

## 🔄 工作流程

每天收盘后（15:10），如果启用参数优化：

1. 加载 `data/picks_history/` 中的所有历史picks
2. 分析 141 个历史推荐的表现
3. 测试 18 个参数组合（快速模式）
4. 生成 `param_optimization_analysis.json`
   - 显示 Top 10 最优参数
   - 与当前参数对比
   - 预期改善空间

## 💾 输出文件

启用后，每天收盘会生成：

```
param_optimization_analysis.json
├── timestamp          // 执行时间
├── overall_winrate    // 总体胜率
├── best_params        // 最优参数组合
├── best_winrate       // 最优胜率
└── top_10             // Top 10 组合
```

## 🚀 使用建议

### 第一周：试运行

```json
"param_optimization_enabled": true
```

- 观察每天生成的 `param_optimization_analysis.json`
- 查看最优参数建议
- 检查是否有改善空间

### 第二周：手动应用

如果最优参数比当前参数有改善：

1. 查看建议的参数组合
2. 手工更新 `quant_core/short_term_strategy.py` 中的参数：

```python
# 第 252 行
SHORT_TERM_TRADING_CONFIG = {
    'rsi_threshold': 25,        # 从当前值改为最优值
    'volume_ratio': 1.3,        # 从当前值改为最优值
    'price_limit': 1.05,        # 从当前值改为最优值
    ...
}
```

3. 重启 `run_alert.py` 应用新参数

### 第三周+：持续优化

- 继续启用参数优化
- 定期检查建议（如有改善 > 2% 则考虑更新）
- 观察实际交易效果

## ⚠️ 注意

1. **首次运行**: 如果 `data/picks_history/` 为空或数据很少，参数优化效果会有限
2. **计算量**: 参数优化在收盘后任务链中运行，会增加 5-10 分钟耗时
3. **可靠性**: 基于历史数据的分析，不一定保证未来表现
4. **手动应用**: 目前生成建议但不自动应用参数（需要手工更新和重启）

## 🔧 高级配置

如果想改变搜索策略：

### 快速测试 (默认，18 个组合，5 分钟)
```python
# 脚本自动使用
param_optimization_analysis.py -c config.json --quick-test
```

### 完整搜索 (120 个组合，30-60 分钟)
```bash
# 手工运行（不走自动化）
.venv/bin/python3 param_optimization_analysis.py -c config.json
```

## 📊 预期效果

| 指标 | 预期改善 |
|------|---------|
| 胜率 | ±2-5% |
| 平均收益 | ±5-15% |
| 年化收益 | ±15-30% |

---

## 常见问题

**Q: 关闭后日志里会显示吗？**
A: 是的，每条自动化任务都会记录，所以如果启用，收盘后的 `run_alert.py` 输出会显示参数优化任务的执行情况。

**Q: 能改成自动应用参数吗？**
A: 目前需要手工更新。后续可以加自动应用功能，但建议先手工验证效果。

**Q: 参数优化和 auto_tune_accuracy 的区别是？**
A: 
- `auto_tune_accuracy` 调整选股过滤阈值（score_range, sell_score）
- `param_optimization` 调整买入信号参数（RSI, 成交量, 价格）

两者相互独立，可同时使用。

---

**生成时间**: 2026-06-03
