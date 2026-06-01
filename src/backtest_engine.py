"""
回测引擎模块
============
核心回测逻辑：每日尾盘筛选买入，次日止盈止损或收盘卖出，统计交易指标。
"""

from collections import defaultdict
import pandas as pd
import numpy as np
from src.utils import logger
from src.feature_engine import calc_features, filter_by_thresholds
from config.settings import STOP_GAIN, STOP_LOSS, MAX_POSITIONS, TAIL_SNAPSHOT_TIME


def run_backtest(
    data_dict: dict, thresholds: dict,
    stop_gain: float = STOP_GAIN, stop_loss: float = STOP_LOSS,
    max_positions: int = MAX_POSITIONS,
) -> dict:
    """
    回测核心逻辑。

    每日尾盘筛选股票 -> 等权买入（最多 max_positions 支）-> 次日止盈/止损/收盘卖出。

    Args:
        data_dict: {stock_code: DataFrame}，需含日期、开盘、收盘、最高、最低、成交量
        thresholds: 因子阈值字典
        stop_gain: 止盈线
        stop_loss: 止损线
        max_positions: 最大持仓数

    Returns:
        dict: 回测统计结果
    """
    logger.info("=" * 60)
    logger.info("回测启动 | 阈值: %s", thresholds)
    logger.info("止盈: %+.1f%% | 止损: %+.1f%% | 最大持仓: %d", stop_gain*100, stop_loss*100, max_positions)
    logger.info("=" * 60)

    daily_snapshots = _build_daily_snapshots(data_dict)
    if not daily_snapshots:
        logger.error("未构建任何交易日快照")
        return _empty_result()

    trade_dates = sorted(daily_snapshots.keys())
    logger.info("回测区间共 %d 个交易日", len(trade_dates))

    trades = []
    holdings = {}

    for i, date in enumerate(trade_dates):
        df_today = daily_snapshots[date]
        df_feat = calc_features(df_today)
        df_selected = filter_by_thresholds(df_feat, thresholds)

        # 卖出持仓（T+1）
        if holdings and i + 1 < len(trade_dates):
            sell_date = trade_dates[i + 1]
            df_next = daily_snapshots.get(sell_date)
            if df_next is not None:
                _process_sell(holdings, df_next, sell_date, stop_gain, stop_loss, trades)
        elif holdings:
            # 最后交易日强制平仓
            for code in list(holdings.keys()):
                row = df_today[df_today["代码"] == code]
                if not row.empty:
                    sell_price = row.iloc[0].get("收盘", row.iloc[0].get("最新价", np.nan))
                    hold = holdings.pop(code)
                    ret = (sell_price - hold["buy_price"]) / hold["buy_price"]
                    trades.append({
                        "code": code, "buy_date": hold["buy_date"], "sell_date": date,
                        "buy_price": hold["buy_price"], "sell_price": sell_price,
                        "return": ret, "hold_days": 1, "exit_reason": "强制平仓",
                    })

        # 买入
        available_slots = max_positions - len(holdings)
        if available_slots > 0 and not df_selected.empty:
            candidates = df_selected[~df_selected["代码"].isin(holdings.keys())]
            if not candidates.empty:
                candidates = candidates.sort_values("ret_1450", ascending=False)
                for _, row in candidates.head(available_slots).iterrows():
                    code = row["代码"]
                    buy_price = row.get("最新价", row.get("收盘", np.nan))
                    if pd.isna(buy_price) or buy_price <= 0:
                        continue
                    holdings[code] = {"buy_price": buy_price, "buy_date": date}
                    logger.debug("买入 %s (%s) 价格: %.2f", row.get("名称", code), code, buy_price)

    result = _compute_statistics(trades)
    logger.info("回测完成 | 交易次数: %d | 胜率: %.2f%%", result["total_trades"], result["win_rate"]*100)
    return result


def _build_daily_snapshots(data_dict: dict) -> dict:
    """将多支股票日线数据按日期组织为每日快照字典。"""
    daily_records = defaultdict(list)
    for code, df_stock in data_dict.items():
        if df_stock is None or df_stock.empty or "日期" not in df_stock.columns:
            continue
        for _, row in df_stock.iterrows():
            date = pd.Timestamp(row["日期"]).strftime("%Y-%m-%d")
            daily_records[date].append({
                "代码": code, "名称": row.get("名称", code),
                "最新价": row.get("收盘", row.get("最新价", np.nan)),
                "开盘": row.get("开盘", np.nan), "最高": row.get("最高", np.nan),
                "最低": row.get("最低", np.nan), "收盘": row.get("收盘", np.nan),
                "成交量": row.get("成交量", 0), "成交额": row.get("成交额", 0),
                "换手率": row.get("换手率", np.nan), "涨跌幅": row.get("涨跌幅", 0.0),
                "流通市值": row.get("流通市值", np.nan),
            })
    result = {}
    for date, records in daily_records.items():
        df = pd.DataFrame(records)
        for col in ["最新价", "开盘", "最高", "最低", "收盘", "换手率", "涨跌幅", "流通市值"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        result[date] = df
    return result


def _process_sell(holdings: dict, df_next: pd.DataFrame, sell_date: str, stop_gain: float, stop_loss: float, trades: list):
    """处理持仓卖出：止盈/止损/收盘卖出。"""
    for code in list(holdings.keys()):
        row = df_next[df_next["代码"] == code]
        if row.empty:
            continue
        hold = holdings.pop(code)
        buy_price = hold["buy_price"]
        high = row.iloc[0].get("最高", np.nan)
        low = row.iloc[0].get("最低", np.nan)
        close = row.iloc[0].get("收盘", row.iloc[0].get("最新价", np.nan))

        high_ret = (high - buy_price) / buy_price if not np.isnan(high) else -999
        low_ret = (low - buy_price) / buy_price if not np.isnan(low) else 999

        if high_ret >= stop_gain:
            sell_price = buy_price * (1 + stop_gain)
            exit_reason = "止盈"
        elif low_ret <= stop_loss:
            sell_price = buy_price * (1 + stop_loss)
            exit_reason = "止损"
        else:
            sell_price = close
            exit_reason = "收盘卖出"

        ret = (sell_price - buy_price) / buy_price
        trades.append({
            "code": code, "buy_date": hold["buy_date"], "sell_date": sell_date,
            "buy_price": buy_price, "sell_price": sell_price,
            "return": ret, "hold_days": 1, "exit_reason": exit_reason,
        })
        logger.debug("卖出 %s | %s | 收益: %+.2f%%", code, exit_reason, ret * 100)


def _compute_statistics(trades: list) -> dict:
    """统计回测结果。"""
    if not trades:
        return _empty_result()
    df_t = pd.DataFrame(trades)
    returns = df_t["return"]
    win = returns > 0
    lose = returns <= 0
    total = len(trades)
    win_cnt = int(win.sum())
    lose_cnt = int(lose.sum())
    win_rate = win_cnt / total if total > 0 else 0
    avg_profit = returns[win].mean() if win_cnt > 0 else 0
    avg_loss = returns[lose].mean() if lose_cnt > 0 else 0
    pf = abs(avg_profit / avg_loss) if avg_loss != 0 else float("inf")
    return {
        "total_trades": total, "win_trades": win_cnt, "lose_trades": lose_cnt,
        "win_rate": win_rate, "avg_profit": avg_profit, "avg_loss": avg_loss,
        "profit_factor": pf, "total_return": returns.sum(), "trades": trades,
    }


def _empty_result() -> dict:
    return {"total_trades": 0, "win_trades": 0, "lose_trades": 0, "win_rate": 0.0,
            "avg_profit": 0.0, "avg_loss": 0.0, "profit_factor": 0.0, "total_return": 0.0, "trades": []}


def print_backtest_result(result: dict):
    """打印回测结果。"""
    print("\n" + "=" * 50)
    print("        回 测 结 果")
    print("=" * 50)
    print(f"  总交易次数:      {result['total_trades']}")
    print(f"  盈利次数:        {result['win_trades']}")
    print(f"  亏损次数:        {result['lose_trades']}")
    print(f"  胜率:            {result['win_rate'] * 100:.2f}%")
    print(f"  平均盈利:        {result['avg_profit'] * 100:+.2f}%")
    print(f"  平均亏损:        {result['avg_loss'] * 100:+.2f}%")
    print(f"  盈亏比:          {result['profit_factor']:.2f}")
    print(f"  总收益率:        {result['total_return'] * 100:+.2f}%")
    print("=" * 50)
