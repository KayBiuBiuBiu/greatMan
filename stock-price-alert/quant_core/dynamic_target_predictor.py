"""动态涨幅预测 - 根据预测目标设定卖点，而非固定百分比"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Any, Optional


class DynamicPriceTargetPredictor:
    """动态价格目标预测器

    不再使用固定的 +3% / +5% 止盈
    而是预测这只股会涨多少，根据预测目标灵活卖出
    """

    @staticmethod
    def predict_target_price_by_resistance(
        df: pd.DataFrame,
        current_price: float,
        lookback_days: int = 20
    ) -> Dict[str, Any]:
        """通过技术位阻力位预测目标价格

        查找 20 日内的关键阻力位（如 20日线、30日线）
        预测股价有可能涨到的位置

        Args:
            df: K线数据
            current_price: 当前股价
            lookback_days: 回看天数

        Returns:
            {
                'resistance_20d': float,      # 20日线阻力位
                'resistance_50d': float,      # 50日线
                'resistance_high': float,     # 20日最高价
                'predicted_target': float,    # 综合预测目标
                'upside_pct': float,         # 预测涨幅 %
                'confidence': str            # 预测可信度
            }
        """
        if len(df) < 50:
            return {'error': '数据不足'}

        close = df['close']
        high = df['high']

        # 计算关键阻力位
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        high_20d = high.tail(20).max()

        # 综合考虑多个阻力位
        resistance_points = [ma20, ma50, high_20d]
        resistance_points = [p for p in resistance_points if p > current_price]

        if not resistance_points:
            # 没有明显阻力位，取当前价上 5%
            predicted_target = current_price * 1.05
            confidence = '低'
        else:
            # 取最近的阻力位作为目标
            predicted_target = min(resistance_points)

            # 评估可信度
            if len(resistance_points) >= 2:
                confidence = '高'  # 多个阻力位一致
            else:
                confidence = '中'

        upside_pct = (predicted_target - current_price) / current_price * 100

        return {
            'method': '技术位阻力',
            'resistance_20d': ma20,
            'resistance_50d': ma50,
            'resistance_high_20d': high_20d,
            'predicted_target': predicted_target,
            'upside_pct': upside_pct,
            'confidence': confidence,
            'current_price': current_price
        }

    @staticmethod
    def predict_target_price_by_history(
        df: pd.DataFrame,
        current_price: float,
        lookback_days: int = 30
    ) -> Dict[str, Any]:
        """通过历史涨幅预测目标价格

        统计这只股过去 N 天的平均涨幅
        假设下次会有类似的涨幅

        Args:
            df: K线数据
            current_price: 当前股价
            lookback_days: 回看天数

        Returns:
            {
                'avg_daily_return': float,   # 平均日收益率
                '10day_avg_return': float,   # 10日平均涨幅
                'predicted_target': float,   # 预测目标
                'upside_pct': float         # 预测涨幅
            }
        """
        if len(df) < lookback_days:
            return {'error': '数据不足'}

        close = df['close']

        # 计算过去 lookback_days 的日收益率
        returns = close.pct_change() * 100  # 转换为百分比
        recent_returns = returns.tail(lookback_days)

        # 统计指标
        avg_daily_return = recent_returns.mean()
        std_daily_return = recent_returns.std()

        # 计算 10 日期间的预期涨幅
        # 假设收益率独立同分布
        days_ahead = 10
        expected_10day_return = avg_daily_return * days_ahead

        # 预测目标价
        predicted_target = current_price * (1 + expected_10day_return / 100)
        upside_pct = expected_10day_return

        return {
            'method': '历史平均涨幅',
            'lookback_days': lookback_days,
            'avg_daily_return': avg_daily_return,
            'std_daily_return': std_daily_return,
            'expected_10day_return': expected_10day_return,
            'predicted_target': predicted_target,
            'upside_pct': upside_pct,
            'current_price': current_price
        }

    @staticmethod
    def predict_target_price_combined(
        df: pd.DataFrame,
        current_price: float
    ) -> Dict[str, Any]:
        """综合多个预测方法

        结合技术位和历史平均，提高预测准确度

        Args:
            df: K线数据
            current_price: 当前股价

        Returns:
            {
                'resistance_prediction': {...},
                'history_prediction': {...},
                'combined_target': float,
                'combined_upside': float,
                'recommended_sell_price': float,  # 推荐卖价 (预测的 95%)
                'stop_loss_price': float         # 止损价 (当前的 -2%)
            }
        """
        # 获取两种预测
        resistance_pred = DynamicPriceTargetPredictor.predict_target_price_by_resistance(df, current_price)
        history_pred = DynamicPriceTargetPredictor.predict_target_price_by_history(df, current_price)

        if 'error' in resistance_pred or 'error' in history_pred:
            return {'error': '数据不足'}

        # 综合两个预测（取平均）
        target1 = resistance_pred.get('predicted_target', current_price)
        target2 = history_pred.get('predicted_target', current_price)

        combined_target = (target1 + target2) / 2
        combined_upside = (combined_target - current_price) / current_price * 100

        # 设置推荐卖价为预测目标的 95%
        # (留下 5% 的容错空间，避免因为短期波动错过目标)
        recommended_sell_price = combined_target * 0.95

        # 止损价
        stop_loss_price = current_price * 0.98  # -2% 止损

        return {
            'resistance_prediction': resistance_pred,
            'history_prediction': history_pred,
            'combined_target': combined_target,
            'combined_upside': combined_upside,
            'recommended_sell_price': recommended_sell_price,
            'stop_loss_price': stop_loss_price,
            'current_price': current_price,
            'summary': f"预测涨 {combined_upside:.1f}%, 目标价 {combined_target:.2f}, 建议卖点 {recommended_sell_price:.2f}"
        }

    @staticmethod
    def should_sell_by_target(
        entry_price: float,
        current_price: float,
        target_price: float,
        stop_loss_price: float,
        days_held: int = 0,
        verbose: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """根据动态目标价决定是否卖出

        Args:
            entry_price: 买入价
            current_price: 当前价
            target_price: 预测目标价
            stop_loss_price: 止损价
            days_held: 持仓天数
            verbose: 是否打印详细信息

        Returns:
            (should_sell, reason, metrics)
        """
        profit_pct = (current_price - entry_price) / entry_price * 100

        metrics = {
            'entry_price': entry_price,
            'current_price': current_price,
            'target_price': target_price,
            'stop_loss_price': stop_loss_price,
            'profit_pct': profit_pct,
            'distance_to_target': (target_price - current_price) / target_price * 100 if target_price > 0 else 0,
            'days_held': days_held
        }

        # 优先级 1: 止损
        if current_price <= stop_loss_price:
            reason = f"止损 {profit_pct:.2f}% (≤ -2%), 保护本金"
            if verbose:
                print(f"⚠️  卖出: {reason}")
            return True, reason, metrics

        # 优先级 2: 达到目标价
        if current_price >= target_price * 0.95:  # 达到目标的 95% 时
            reason = f"达到目标价 {target_price:.2f}, 实现 {profit_pct:.2f}% 收益"
            if verbose:
                print(f"✅ 卖出: {reason}")
            return True, reason, metrics

        # 优先级 3: 时间到期
        if days_held >= 10:
            reason = f"10日到期 (持仓{days_held}天), 无条件平仓"
            if verbose:
                print(f"⏰ 卖出: {reason}")
            return True, reason, metrics

        # 继续持仓
        distance = metrics['distance_to_target']
        reason = f"继续持仓 (距目标还有 {distance:.1f}%, 当前 +{profit_pct:.2f}%)"
        if verbose:
            print(f"📊 持仓: {reason}")

        return False, reason, metrics


# 配置
DYNAMIC_TARGET_CONFIG = {
    'prediction_methods': ['resistance', 'history', 'combined'],
    'target_buffer': 0.95,      # 预测目标打 95% 折扣作为卖点
    'stop_loss_pct': -2.0,      # 止损 -2%
    'max_hold_days': 10,        # 最长持仓 10 天
    'lookback_for_history': 30, # 历史涨幅回看 30 天
    'lookback_for_resistance': 20  # 技术位回看 20 天
}


if __name__ == '__main__':
    # 测试代码
    import sys
    sys.path.insert(0, '/Users/haha/greatMan/stock-price-alert')

    from quant_core.selector import load_df

    print("=" * 70)
    print("🧪 测试动态目标价预测")
    print("=" * 70)

    df = load_df("600711", lookback=60)
    if df is not None and len(df) > 0:
        current_price = df['close'].iloc[-1]
        print(f"\n股票: 600711, 当前价: {current_price:.2f}")

        # 预测
        prediction = DynamicPriceTargetPredictor.predict_target_price_combined(df, current_price)

        print(f"\n【预测结果】")
        print(f"  {prediction.get('summary', 'N/A')}")

        print(f"\n【技术位预测】")
        rp = prediction.get('resistance_prediction', {})
        print(f"  阻力位: 20日线 {rp.get('resistance_20d', 0):.2f}, " +
              f"目标 {rp.get('predicted_target', 0):.2f} " +
              f"(涨 {rp.get('upside_pct', 0):.1f}%)")

        print(f"\n【历史涨幅预测】")
        hp = prediction.get('history_prediction', {})
        print(f"  历史平均日收益: {hp.get('avg_daily_return', 0):.2f}%")
        print(f"  预期 10日涨幅: {hp.get('expected_10day_return', 0):.1f}%")
        print(f"  目标价: {hp.get('predicted_target', 0):.2f}")

        print(f"\n【推荐卖点】")
        print(f"  目标价: {prediction.get('combined_target', 0):.2f}")
        print(f"  推荐卖价: {prediction.get('recommended_sell_price', 0):.2f}")
        print(f"  止损价: {prediction.get('stop_loss_price', 0):.2f}")

        # 测试卖出信号
        print(f"\n【测试卖出信号】")

        test_cases = [
            (current_price * 0.98, "跌 2% (到止损)"),
            (current_price * 1.02, "涨 2% (未到目标)"),
            (prediction.get('recommended_sell_price', 0), "达到推荐卖价"),
        ]

        for test_price, desc in test_cases:
            should_exit, reason, metrics = DynamicPriceTargetPredictor.should_sell_by_target(
                entry_price=current_price,
                current_price=test_price,
                target_price=prediction.get('combined_target', 0),
                stop_loss_price=prediction.get('stop_loss_price', 0),
                verbose=True
            )
            print(f"  场景: {desc} ({test_price:.2f})")
            print(f"  结果: {reason}\n")
