"""
每日选股主程序
==============
获取实时行情，用最优阈值筛选，按凯利公式计算仓位。
"""

from typing import Optional
import pandas as pd
import numpy as np
from src.utils import logger
from src.data_fetcher import get_realtime_quotes
from src.feature_engine import calc_features, filter_by_thresholds
from config.settings import TOTAL_CAPITAL, MAX_POSITIONS, OVERHEAT_LIMIT, BEST_THRESHOLDS, BACKTEST_WIN_RATE, BACKTEST_PROFIT_FACTOR


def kelly_position_size(win_rate: float, profit_factor: float, total_capital: float, max_position_ratio: float = 0.15) -> dict:
    """
    根据凯利公式计算仓位。
    f = (P * B - (1-P)) / B
    实际使用半凯利 (f/2) 和 1/4 凯利 (f/4)。

    Args:
        win_rate: 胜率 (0~1)
        profit_factor: 盈亏比
        total_capital: 总资金
        max_position_ratio: 单支股票最大仓位比例

    Returns:
        dict: full_kelly, half_kelly, quarter_kelly, capped 金额
    """
    if profit_factor <= 0 or win_rate <= 0 or win_rate >= 1:
        logger.warning("凯利参数无效，使用保守仓位")
        return {"full_kelly": 0, "half_kelly": 0, "quarter_kelly": 0, "capped": 0}

    f = (win_rate * profit_factor - (1 - win_rate)) / profit_factor
    f = max(0, f)

    full = f * total_capital
    half = f * 0.5 * total_capital
    quarter = f * 0.25 * total_capital
    max_per = total_capital * max_position_ratio
    capped = min(half, max_per)

    return {
        "full_kelly": round(full, 2), "half_kelly": round(half, 2),
        "quarter_kelly": round(quarter, 2), "capped": round(capped, 2),
    }


def daily_pick(win_rate: float = BACKTEST_WIN_RATE, profit_factor: float = BACKTEST_PROFIT_FACTOR,
               thresholds: Optional[dict] = None, total_capital: float = TOTAL_CAPITAL) -> pd.DataFrame:
    """
    每日选股主逻辑。

    流程：获取行情 -> 计算特征 -> 阈值筛选 -> 过热检查 -> 凯利仓位计算。

    Returns:
        DataFrame，空表示空仓。
    """
    if thresholds is None:
        thresholds = BEST_THRESHOLDS

    logger.info("=" * 60)
    logger.info("每日选股启动 | 资金: %.0f | 胜率: %.2f%% | 盈亏比: %.2f", total_capital, win_rate*100, profit_factor)
    logger.info("=" * 60)

    try:
        df_quote = get_realtime_quotes()
    except Exception as e:
        logger.error("获取实时行情失败: %s", e)
        return pd.DataFrame()

    if df_quote.empty:
        logger.error("实时行情数据为空")
        return pd.DataFrame()

    df_feat = calc_features(df_quote)
    df_selected = filter_by_thresholds(df_feat, thresholds)

    if len(df_selected) > OVERHEAT_LIMIT:
        logger.warning("市场过热！候选 %d 支 > %d，放弃交易。", len(df_selected), OVERHEAT_LIMIT)
        return pd.DataFrame()

    if df_selected.empty:
        logger.info("无股票通过筛选。")
        return pd.DataFrame()

    df_selected = df_selected.sort_values(["close_position", "ret_1450"], ascending=[False, False])
    df_final = df_selected.head(MAX_POSITIONS).copy()

    buy_amounts = []
    for _, row in df_final.iterrows():
        pos = kelly_position_size(win_rate, profit_factor, total_capital)
        price = row.get("最新价", 10)
        for key in ["full_kelly", "half_kelly", "quarter_kelly", "capped"]:
            amt = pos[key]
            if price > 0:
                shares = max(100, int(amt / price / 100) * 100)
                pos[f"{key}_shares"] = shares
                pos[f"{key}_amount"] = round(shares * price, 2)
        buy_amounts.append(pos)

    df_buy = pd.DataFrame(buy_amounts)
    df_final = pd.concat([df_final.reset_index(drop=True), df_buy], axis=1)
    logger.info("选股完成: %d 支股票入选", len(df_final))
    return df_final


def format_pick_result(df: pd.DataFrame) -> str:
    """格式化选股结果为可读文本。"""
    if df.empty:
        return "今日无尾盘买入信号，建议空仓。"

    lines = []
    lines.append("=" * 70)
    lines.append("A股尾盘买入策略 - 今日选股报告")
    lines.append("=" * 70)
    lines.append(f"{'代码':<8} {'名称':<8} {'建议买入':<10} {'半凯利':<10} {'1/4凯利':<10} {'涨幅%':<7} {'量比':<7} {'换手率%':<7}")
    lines.append("-" * 70)
    for _, row in df.iterrows():
        lines.append(
            f"{str(row.get('代码', '')):<8} "
            f"{str(row.get('名称', '')):<8} "
            f"{row.get('capped_amount', 0):<10,.0f} "
            f"{row.get('half_kelly_amount', 0):<10,.0f} "
            f"{row.get('quarter_kelly_amount', 0):<10,.0f} "
            f"{row.get('ret_1450', 0):<7.2f} "
            f"{row.get('volume_ratio', 0):<7.2f} "
            f"{row.get('turnover_rate', 0):<7.2f}"
        )
    lines.append("=" * 70)
    return "\n".join(lines)
