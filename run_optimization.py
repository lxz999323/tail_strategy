#!/usr/bin/env python3
"""
A股尾盘买入策略 - 因子优化入口
=================================
用法: python run_optimization.py
      python run_optimization.py --sample 100 --top 10
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import logger
from src.data_fetcher import get_all_history_data, get_realtime_quotes
from src.factor_optimizer import PARAM_GRID, grid_search_optimize, print_top_results, update_settings_best
from config.settings import BACKTEST_START, BACKTEST_END


def main():
    parser = argparse.ArgumentParser(description="因子参数优化")
    parser.add_argument("--start", default=BACKTEST_START)
    parser.add_argument("--end", default=BACKTEST_END)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=10)
    parser.add_argument("--sample", type=int, default=200)
    args = parser.parse_args()

    logger.info("因子优化: %s ~ %s, sample=%d", args.start, args.end, args.sample)

    try:
        df_all = get_realtime_quotes()
        stock_codes = df_all["代码"].astype(str).tolist()[:args.sample]
    except Exception as e:
        logger.warning("获取列表失败，使用内置池: %s", e)
        stock_codes = ["000001","000002","000333","000651","000858",
                       "002415","300059","300750","600000","600036",
                       "600519","600887","600900","601166","601318",
                       "601398","601899","000568","600030","600585"]

    data_dict = get_all_history_data(stock_codes, args.start, args.end)
    if not data_dict:
        logger.error("无有效历史数据")
        return

    top_results = grid_search_optimize(data_dict, top_n=args.top, min_trades=args.min_trades)
    if not top_results:
        logger.error("未找到有效参数组合")
        return

    print_top_results(top_results)

    choice = input("\n是否将最优参数写入 config/settings.py？(1=是, 2=否): ").strip()
    if choice == "1":
        update_settings_best(top_results[0])
        print(f"✓ 已更新: 胜率={top_results[0]['win_rate']:.4f}, 盈亏比={top_results[0]['profit_factor']:.4f}")


if __name__ == "__main__":
    main()
