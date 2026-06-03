"""分析股票预测准确率"""
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

# 读取交易日志
trade_log_path = Path("trade_log.json")
if not trade_log_path.exists():
    print("❌ 未找到 trade_log.json")
    exit(1)

with open(trade_log_path) as f:
    trades = json.load(f)

print("=" * 70)
print("📊 股票预测准确率分析")
print("=" * 70)

# 统计买卖记录
buy_records = defaultdict(list)  # {code: [买入记录]}
sell_records = defaultdict(list)  # {code: [卖出记录]}

for trade in trades:
    code = trade.get("code")
    trade_type = trade.get("type")
    date_str = trade.get("date")
    price = trade.get("price", 0)
    
    if not code or not date_str:
        continue
    
    if trade_type == "buy":
        buy_records[code].append({
            "date": date_str,
            "price": price,
            "trade": trade
        })
    elif trade_type == "sell":
        sell_records[code].append({
            "date": date_str,
            "price": price,
            "trade": trade
        })

# 计算交易对的收益率
profits = []
losses = []
breakevens = []

for code in buy_records:
    buys = sorted(buy_records[code], key=lambda x: x["date"])
    sells = sorted(sell_records.get(code, []), key=lambda x: x["date"])
    
    buy_idx = 0
    for sell in sells:
        while buy_idx < len(buys) and buys[buy_idx]["date"] < sell["date"]:
            buy_idx += 1
        
        if buy_idx > 0:
            prev_buy = buys[buy_idx - 1]
            profit_pct = (sell["price"] - prev_buy["price"]) / prev_buy["price"] * 100
            
            record = {
                "code": code,
                "buy_date": prev_buy["date"],
                "buy_price": prev_buy["price"],
                "sell_date": sell["date"],
                "sell_price": sell["price"],
                "profit_pct": profit_pct
            }
            
            if profit_pct > 0:
                profits.append(record)
            elif profit_pct < 0:
                losses.append(record)
            else:
                breakevens.append(record)

print(f"\n📈 交易统计:")
print(f"  总交易对数: {len(profits) + len(losses) + len(breakevens)}")
print(f"  盈利交易: {len(profits)}")
print(f"  亏损交易: {len(losses)}")
print(f"  平局交易: {len(breakevens)}")

total_trades = len(profits) + len(losses)
if total_trades > 0:
    win_rate = len(profits) / total_trades * 100
    print(f"\n🎯 预测成功率: {win_rate:.1f}%")
else:
    print(f"\n❌ 数据不足，无法计算成功率")

if profits:
    avg_profit = sum(p["profit_pct"] for p in profits) / len(profits)
    max_profit = max(p["profit_pct"] for p in profits)
    print(f"\n💰 盈利交易:")
    print(f"  平均收益: {avg_profit:.2f}%")
    print(f"  最大收益: {max_profit:.2f}%")
    print(f"  前5大盈利:")
    for i, p in enumerate(sorted(profits, key=lambda x: x["profit_pct"], reverse=True)[:5], 1):
        print(f"    {i}. {p['code']} {p['buy_date']}-{p['sell_date']}: +{p['profit_pct']:.2f}%")

if losses:
    avg_loss = sum(l["profit_pct"] for l in losses) / len(losses)
    max_loss = min(l["profit_pct"] for l in losses)
    print(f"\n📉 亏损交易:")
    print(f"  平均亏损: {avg_loss:.2f}%")
    print(f"  最大亏损: {max_loss:.2f}%")
    print(f"  前5大亏损:")
    for i, l in enumerate(sorted(losses, key=lambda x: x["profit_pct"])[:5], 1):
        print(f"    {i}. {l['code']} {l['buy_date']}-{l['sell_date']}: {l['profit_pct']:.2f}%")

# 按股票统计
code_stats = defaultdict(lambda: {"win": 0, "loss": 0, "profit": 0})
for p in profits:
    code_stats[p["code"]]["win"] += 1
    code_stats[p["code"]]["profit"] += p["profit_pct"]
for l in losses:
    code_stats[l["code"]]["loss"] += 1
    code_stats[l["code"]]["profit"] += l["profit_pct"]

print(f"\n📋 按股票统计 (前10):")
sorted_codes = sorted(code_stats.items(), 
                     key=lambda x: x[1]["win"]/(x[1]["win"]+x[1]["loss"]) if x[1]["win"]+x[1]["loss"] > 0 else 0,
                     reverse=True)

for code, stats in sorted_codes[:10]:
    total = stats["win"] + stats["loss"]
    if total > 0:
        rate = stats["win"] / total * 100
        avg = stats["profit"] / total
        print(f"  {code}: 成功率 {rate:.1f}% ({stats['win']}/{total}), 平均 {avg:+.2f}%")

# 查看最近交易
print(f"\n⏰ 最近交易 (20条):")
recent = sorted(trades, key=lambda x: x.get("date", ""), reverse=True)[:20]
for trade in recent:
    code = trade.get("code", "?")
    trade_type = trade.get("type", "?")
    date = trade.get("date", "?")
    price = trade.get("price", 0)
    reason = trade.get("reason", "")[:40]
    print(f"  {date} {code} {trade_type:4} @ {price:7.2f} {reason}")

