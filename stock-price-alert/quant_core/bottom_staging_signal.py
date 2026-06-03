"""分阶段底部布局 - 从底部就开始有买入信号"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Any


class BottomStagingSignal:
    """分阶段底部布局信号生成器

    不再等到金叉才买（那时反弹已经进行了）
    而是在底部就开始有信号，分三阶段布局
    """

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """计算 RSI 指标"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def detect_stage1_bottom(df: pd.DataFrame, verbose: bool = False) -> Dict[str, Any]:
        """检测第1阶段：底部确认信号

        条件：
          1. 价格跌穿 20日均线 10% 以上
          2. RSI < 20（极度超卖，不是 < 35）
          3. 出现止跌信号（长下影线或成交量止跌回升）

        Action: 买入 1/3 头寸（轻仓试探）
        """
        if len(df) < 50:
            return {'signal': False, 'reason': '数据不足'}

        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        # 当前指标
        current_price = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        rsi = BottomStagingSignal.calculate_rsi(close, 14)
        current_rsi = rsi.iloc[-1]

        # 条件1：价格跌穿 20日线 10%
        drop_below_ma20 = current_price < ma20 * 0.90
        drop_pct = (1 - current_price / ma20) * 100

        if not drop_below_ma20:
            if verbose:
                print(f"❌ 未跌穿20日线10%: 当前{drop_pct:.1f}%")
            return {
                'signal': False,
                'reason': f'未跌穿20日线10% (只跌{drop_pct:.1f}%)',
                'stage': 1
            }

        # 条件2：RSI 极度超卖 (< 20)
        rsi_extreme_oversold = current_rsi < 20

        if not rsi_extreme_oversold:
            if verbose:
                print(f"❌ RSI未极度超卖: {current_rsi:.1f}")
            return {
                'signal': False,
                'reason': f'RSI未极度超卖 (RSI={current_rsi:.1f})',
                'stage': 1
            }

        # 条件3：出现止跌信号
        # 用高低价的距离代替开盘价 (无open数据)
        # 长下影线：低点离高点很远，说明有止跌
        range_ratio = (high.iloc[-1] - low.iloc[-1]) / high.iloc[-1]
        low_ratio = (high.iloc[-1] - low.iloc[-1]) / (close.iloc[-1] - low.iloc[-1] + 0.01)
        has_long_shadow = low_ratio > 1.5  # 下影线占比较大

        # 或者成交量止跌回升
        vol_avg_5d = volume.tail(6)[:-1].mean()
        vol_today = volume.iloc[-1]
        volume_recovery = vol_today > vol_avg_5d * 0.8  # 成交量不再萎缩

        has_stop_signal = has_long_shadow or volume_recovery

        if not has_stop_signal:
            if verbose:
                print(f"❌ 未出现止跌信号")
            return {
                'signal': False,
                'reason': '未出现止跌信号',
                'stage': 1
            }

        # 所有条件都满足
        if verbose:
            print("✅ 第1阶段：底部确认")
            print(f"   跌穿20日线: {drop_pct:.1f}%")
            print(f"   RSI: {current_rsi:.1f}")
            print(f"   止跌信号: 长下影线={has_long_shadow}, 成交量回升={volume_recovery}")

        return {
            'signal': True,
            'stage': 1,
            'reason': '底部确认',
            'buy_pct': 0.10,  # 买入 10% 资金
            'stop_loss_pct': -5.0,  # 止损 -5%
            'price': current_price,
            'rsi': current_rsi,
            'ma20': ma20,
            'drop_pct': drop_pct,
            'recommendation': f'轻仓买入1/3，止损在 {current_price * 0.95:.2f}'
        }

    @staticmethod
    def detect_stage2_support(df: pd.DataFrame, stage1_price: float, verbose: bool = False) -> Dict[str, Any]:
        """检测第2阶段：支撑确认信号

        条件：
          1. 反弹后再次下跌（不是继续上涨）
          2. 但没有破底（止跌有效）
          3. RSI 再次进入超卖区 (< 30)

        Action: 加仓到 2/3
        """
        if len(df) < 20:
            return {'signal': False, 'reason': '数据不足'}

        close = df['close']
        current_price = close.iloc[-1]
        rsi = BottomStagingSignal.calculate_rsi(close, 14)
        current_rsi = rsi.iloc[-1]

        # 条件1：在底部附近反复（±5% 范围内）
        near_bottom = stage1_price * 0.95 < current_price < stage1_price * 1.05
        distance_to_bottom = ((current_price - stage1_price) / stage1_price) * 100

        if not near_bottom:
            if verbose:
                print(f"❌ 未在底部附近: 距离{distance_to_bottom:+.1f}%")
            return {
                'signal': False,
                'reason': f'不在底部附近 (距离{distance_to_bottom:+.1f}%)',
                'stage': 2
            }

        # 条件2：RSI 再次超卖
        rsi_oversold = current_rsi < 30

        if not rsi_oversold:
            if verbose:
                print(f"❌ RSI不超卖: {current_rsi:.1f}")
            return {
                'signal': False,
                'reason': f'RSI不超卖 (RSI={current_rsi:.1f})',
                'stage': 2
            }

        # 所有条件都满足
        if verbose:
            print("✅ 第2阶段：支撑确认")
            print(f"   在底部附近: {distance_to_bottom:+.1f}%")
            print(f"   RSI: {current_rsi:.1f}")

        return {
            'signal': True,
            'stage': 2,
            'reason': '支撑确认',
            'buy_pct': 0.10,  # 再买 10%，累计 20%
            'price': current_price,
            'rsi': current_rsi,
            'avg_cost': (stage1_price + current_price) / 2,
            'recommendation': f'加仓1/3，平均成本 {(stage1_price + current_price) / 2:.2f}'
        }

    @staticmethod
    def detect_stage3_rebound(df: pd.DataFrame, verbose: bool = False) -> Dict[str, Any]:
        """检测第3阶段：反弹启动信号

        条件：
          1. 5日均线穿过10日均线（金叉）
          2. RSI 脱离超卖区 (接近 35)
          3. 成交量配合

        Action: 加仓到满仓 (1/3)
        """
        if len(df) < 20:
            return {'signal': False, 'reason': '数据不足'}

        close = df['close']
        volume = df['volume']

        # 计算均线
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()

        # 条件1：金叉
        golden_cross = (ma5.iloc[-2] <= ma10.iloc[-2]) and (ma5.iloc[-1] > ma10.iloc[-1])

        if not golden_cross:
            if verbose:
                print(f"❌ 未金叉: ma5={ma5.iloc[-1]:.2f}, ma10={ma10.iloc[-1]:.2f}")
            return {
                'signal': False,
                'reason': '未出现金叉',
                'stage': 3
            }

        # 条件2：RSI 脱离超卖
        rsi = BottomStagingSignal.calculate_rsi(close, 14)
        current_rsi = rsi.iloc[-1]
        rsi_recovering = current_rsi > 30

        if not rsi_recovering:
            if verbose:
                print(f"❌ RSI未脱离超卖: {current_rsi:.1f}")
            return {
                'signal': False,
                'reason': f'RSI未脱离超卖 (RSI={current_rsi:.1f})',
                'stage': 3
            }

        # 条件3：成交量配合
        vol_avg_5d = volume.tail(6)[:-1].mean()
        vol_today = volume.iloc[-1]
        volume_ratio = vol_today / vol_avg_5d if vol_avg_5d > 0 else 0
        volume_good = volume_ratio > 1.2

        if not volume_good:
            if verbose:
                print(f"⚠️  成交量一般: {volume_ratio:.2f}x")
            # 成交量不好不拒绝，只是打个警告

        if verbose:
            print("✅ 第3阶段：反弹启动")
            print(f"   金叉: ma5={ma5.iloc[-1]:.2f} > ma10={ma10.iloc[-1]:.2f}")
            print(f"   RSI: {current_rsi:.1f}")
            print(f"   成交量: {volume_ratio:.2f}x")

        return {
            'signal': True,
            'stage': 3,
            'reason': '反弹启动',
            'buy_pct': 0.80,  # 买入剩余 80%，加到满仓
            'price': close.iloc[-1],
            'rsi': current_rsi,
            'ma5': ma5.iloc[-1],
            'ma10': ma10.iloc[-1],
            'volume_ratio': volume_ratio,
            'recommendation': '加仓到满仓，确认反弹启动'
        }


# 使用示例
if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/Users/haha/greatMan/stock-price-alert')

    from quant_core.selector import load_df

    print("=" * 70)
    print("🧪 分阶段底部布局信号测试")
    print("=" * 70)

    df = load_df("600711", lookback=60)
    if df is not None and len(df) > 0:
        print(f"\n当前价: {df['close'].iloc[-1]:.2f}")

        # 第1阶段
        print("\n【第1阶段：底部确认】")
        stage1 = BottomStagingSignal.detect_stage1_bottom(df, verbose=True)
        if stage1['signal']:
            print(f"✅ 信号: {stage1['reason']}")
            print(f"   建议: {stage1['recommendation']}")

        # 第2阶段（假设第1阶段已触发）
        if stage1['signal']:
            print("\n【第2阶段：支撑确认】")
            print("(需要反弹后再次下跌，测试中略过)")

        # 第3阶段
        print("\n【第3阶段：反弹启动】")
        stage3 = BottomStagingSignal.detect_stage3_rebound(df, verbose=True)
        if stage3['signal']:
            print(f"✅ 信号: {stage3['reason']}")
            print(f"   建议: {stage3['recommendation']}")
        else:
            print(f"❌ {stage3['reason']}")
