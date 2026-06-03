"""10交易日短期交易策略 - 进出信号生成器"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any


class ShortTermTradingSignal:
    """10日交易周期的进出信号"""

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """计算 RSI 指标

        RSI = 100 - 100 / (1 + RS)
        其中 RS = 平均涨幅 / 平均跌幅

        Args:
            prices: 收盘价序列
            period: 周期，默认 14

        Returns:
            RSI 序列
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def get_entry_signal(df: pd.DataFrame, verbose: bool = False) -> Dict[str, Any]:
        """判断是否应该买入

        进场规则:
          1. 日线 5日/10日均线金叉 (短期均线走强)
          2. RSI(14) < 35 (相对超卖)
          3. 成交量相比前5日平均 > 1.5倍 (资金推动)
          4. 股价 < 20日均线 × 1.1 (不在极高位)

        Args:
            df: K线数据，columns 需要包含 high, low, close, volume
            verbose: 是否打印详细信息

        Returns:
            {
                'signal': True/False,
                'conditions': {
                    'golden_cross': True/False,
                    'rsi_oversold': True/False,
                    'volume_surge': True/False,
                    'price_valid': True/False
                },
                'rsi': float,
                'ma5': float,
                'ma10': float,
                'ma20': float,
                'price': float,
                'volume_ratio': float
            }
        """
        if len(df) < 20:
            return {'signal': False, 'reason': '数据不足，需要至少 20 根 K线'}

        conditions = {}

        # 1. 均线金叉检查
        ma5 = df['close'].rolling(5).mean()
        ma10 = df['close'].rolling(10).mean()

        # 5日均线穿过10日均线（金叉）
        golden_cross = (ma5.iloc[-2] <= ma10.iloc[-2]) and (ma5.iloc[-1] > ma10.iloc[-1])
        conditions['golden_cross'] = golden_cross

        if not golden_cross:
            if verbose:
                print(f"❌ 均线未金叉: ma5={ma5.iloc[-1]:.2f}, ma10={ma10.iloc[-1]:.2f}")
            return {'signal': False, 'reason': '均线未金叉', 'conditions': conditions}

        # 2. RSI 超卖检查
        rsi = ShortTermTradingSignal.calculate_rsi(df['close'], period=14)
        rsi_oversold = rsi.iloc[-1] < 35
        conditions['rsi_oversold'] = rsi_oversold

        if not rsi_oversold:
            if verbose:
                print(f"❌ RSI 未超卖: rsi={rsi.iloc[-1]:.1f}")
            return {'signal': False, 'reason': f'RSI 未超卖 ({rsi.iloc[-1]:.1f})', 'conditions': conditions}

        # 3. 成交量确认
        volume_avg_5d = df['volume'].tail(6)[:-1].mean()
        volume_today = df['volume'].iloc[-1]

        volume_ratio = volume_today / volume_avg_5d if volume_avg_5d > 0 else 0
        volume_surge = volume_ratio > 1.5
        conditions['volume_surge'] = volume_surge

        if not volume_surge:
            if verbose:
                print(f"❌ 成交量未突破: ratio={volume_ratio:.2f}")
            return {'signal': False, 'reason': f'成交量未突破 ({volume_ratio:.2f}x)', 'conditions': conditions}

        # 4. 价格位置检查
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        price_today = df['close'].iloc[-1]

        price_not_too_high = price_today < ma20 * 1.1
        conditions['price_valid'] = price_not_too_high

        if not price_not_too_high:
            if verbose:
                print(f"❌ 价格过高: price={price_today:.2f}, ma20*1.1={ma20*1.1:.2f}")
            return {'signal': False, 'reason': '价格过高', 'conditions': conditions}

        if verbose:
            print("✅ 进场信号满足所有条件")
            print(f"   均线: ma5={ma5.iloc[-1]:.2f} > ma10={ma10.iloc[-1]:.2f}")
            print(f"   RSI: {rsi.iloc[-1]:.1f} < 35")
            print(f"   成交量: {volume_ratio:.2f}x > 1.5x")
            print(f"   价格: {price_today:.2f} < ma20*1.1={ma20*1.1:.2f}")

        return {
            'signal': True,
            'reason': '所有条件满足，可以买入',
            'conditions': conditions,
            'rsi': rsi.iloc[-1],
            'ma5': ma5.iloc[-1],
            'ma10': ma10.iloc[-1],
            'ma20': ma20,
            'price': price_today,
            'volume_ratio': volume_ratio
        }

    @staticmethod
    def get_exit_signal(
        entry_price: float,
        current_price: float,
        days_held: int,
        df: pd.DataFrame = None,
        verbose: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """判断是否应该卖出

        出场规则 (按优先级):
          1. 止盈 +5% - 落袋为安
          2. 止盈 +3% - 立即卖出
          3. 止损 -3% - 必须保护本金
          4. 止损 -2% - 防止继续下跌
          5. 时间到期 (10天) - 无条件平仓
          6. 均线反转 - 避免反转亏损

        Args:
            entry_price: 买入价格
            current_price: 当前价格
            days_held: 持仓天数
            df: K线数据（可选，用于检查均线反转）
            verbose: 是否打印详细信息

        Returns:
            (should_exit, reason, metrics)
        """
        profit_pct = (current_price - entry_price) / entry_price * 100

        metrics = {
            'profit_pct': profit_pct,
            'entry_price': entry_price,
            'current_price': current_price,
            'days_held': days_held
        }

        # 止盈规则 (最优先)
        if profit_pct >= 5:
            reason = f"止盈 +{profit_pct:.2f}% (≥5%), 落袋为安"
            if verbose:
                print(f"✅ 卖出信号: {reason}")
            return True, reason, metrics

        if profit_pct >= 3:
            reason = f"止盈 +{profit_pct:.2f}% (≥3%), 立即卖出"
            if verbose:
                print(f"✅ 卖出信号: {reason}")
            return True, reason, metrics

        # 止损规则
        if profit_pct <= -3:
            reason = f"止损 {profit_pct:.2f}% (≤-3%), 必须保护本金"
            if verbose:
                print(f"⚠️  卖出信号: {reason}")
            return True, reason, metrics

        if profit_pct <= -2:
            reason = f"止损 {profit_pct:.2f}% (≤-2%), 防止继续下跌"
            if verbose:
                print(f"⚠️  卖出信号: {reason}")
            return True, reason, metrics

        # 时间规则
        if days_held >= 10:
            reason = f"10日到期 (持仓{days_held}天), 无条件平仓 (收益{profit_pct:.2f}%)"
            if verbose:
                print(f"⏰ 卖出信号: {reason}")
            return True, reason, metrics

        # 技术面反转 (均线转弱)
        if df is not None and len(df) >= 10:
            ma5 = df['close'].rolling(5).mean()
            ma10 = df['close'].rolling(10).mean()

            # 当 5日均线跌破 10日均线时卖出
            if ma5.iloc[-1] < ma10.iloc[-1]:
                # 但只在有一定损失时才这样做，避免频繁止损
                if profit_pct < 0:
                    reason = f"均线反转 (ma5<ma10), 避免进一步亏损 (当前{profit_pct:.2f}%)"
                    if verbose:
                        print(f"📉 卖出信号: {reason}")
                    return True, reason, metrics

        # 继续持仓
        reason = f"继续持仓 (收益{profit_pct:+.2f}%, 持仓{days_held}天)"
        if verbose:
            print(f"📊 继续持仓: {reason}")

        return False, reason, metrics

    @staticmethod
    def format_signal(signal_dict: Dict[str, Any]) -> str:
        """格式化信号输出为可读的文本"""
        if not signal_dict.get('signal'):
            return f"❌ 不买入: {signal_dict.get('reason', '未知原因')}"

        lines = ["✅ 买入信号满足条件:"]
        conditions = signal_dict.get('conditions', {})

        if conditions.get('golden_cross'):
            lines.append(f"  • 均线金叉: ma5={signal_dict.get('ma5', 0):.2f} > ma10={signal_dict.get('ma10', 0):.2f}")

        if conditions.get('rsi_oversold'):
            lines.append(f"  • RSI 超卖: {signal_dict.get('rsi', 0):.1f} < 35")

        if conditions.get('volume_surge'):
            lines.append(f"  • 成交量突增: {signal_dict.get('volume_ratio', 0):.2f}x")

        if conditions.get('price_valid'):
            lines.append(f"  • 价格合理: {signal_dict.get('price', 0):.2f}")

        return "\n".join(lines)


# 风控参数
SHORT_TERM_TRADING_CONFIG = {
    'stop_loss_pct': -2.0,           # 止损点 -2%
    'take_profit_target1': 3.0,      # 第一止盈 +3%
    'take_profit_target2': 5.0,      # 第二止盈 +5%
    'max_hold_days': 10,             # 最长持仓 10 天
    'max_position_pct': 10,          # 单只最多 10% 资金
    'max_total_position_pct': 50,    # 总持仓最多 50% 资金
    'max_concurrent_positions': 5,   # 同时最多 5 只
}


if __name__ == '__main__':
    # 测试代码
    import sys
    sys.path.insert(0, '/Users/haha/greatMan/stock-price-alert')

    from quant_core.selector import load_df

    # 测试进场信号
    print("=" * 70)
    print("🧪 测试进场信号")
    print("=" * 70)

    df = load_df("600711", lookback=50)
    if df is not None:
        signal = ShortTermTradingSignal.get_entry_signal(df, verbose=True)
        print(f"\n结果: {ShortTermTradingSignal.format_signal(signal)}")

    # 测试出场信号
    print("\n" + "=" * 70)
    print("🧪 测试出场信号")
    print("=" * 70)

    test_cases = [
        (12.50, 12.37, 2, "止损 -2.5%"),
        (12.50, 12.88, 3, "止盈 +3%"),
        (12.50, 13.13, 4, "止盈 +5%"),
        (12.50, 12.70, 10, "时间到期"),
        (12.50, 12.65, 5, "继续持仓"),
    ]

    for entry, current, days, desc in test_cases:
        should_exit, reason, metrics = ShortTermTradingSignal.get_exit_signal(
            entry, current, days, verbose=True
        )
        print(f"  → {reason}\n")
