#!/usr/bin/env python3
"""
A股尾盘买入策略 - 回测入口
=============================
用法: python run_backtest.py
      python run_backtest.py --start 2022-01-01 --end 2023-12-31
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import logger
from src.data_fetcher import get_all_history_data, get_realtime_quotes
from src.backtest_engine import run_backtest, print_backtest_result
from config.settings import BEST_THRESHOLDS, BACKTEST_START, BACKTEST_END


def main():
    parser = argparse.ArgumentParser(description="A股尾盘买入策略 - 回测")
    parser.add_argument("--start", default=BACKTEST_START)
    parser.add_argument("--end", default=BACKTEST_END)
    parser.add_argument("--codes", nargs="+", default=None)
    parser.add_argument("--sample", type=int, default=500, help="使用前 N 支股票")
    args = parser.parse_args()

    logger.info("回测: %s ~ %s", args.start, args.end)

    if args.codes:
        stock_codes = args.codes
    else:
        logger.info("获取股票列表...")
        try:
            df_all = get_realtime_quotes()
            stock_codes = df_all["代码"].astype(str).tolist()[:args.sample]
            logger.info("使用前 %d 支股票", len(stock_codes))
        except Exception as e:
            logger.warning("获取列表失败: %s，使用内置股票池", e)
            stock_codes = [
                "000001","000002","000333","000651","000858","002415","002714",
                "300059","300750","600000","600036","600276","600519","600887",
                "600900","601012","601166","601318","601398","601899",
                "603259","000568","002304","300124","600030","600585",
                "600809","601088","601628","601857",
            ]

    data_dict = get_all_history_data(stock_codes, args.start, args.end)
    if not data_dict:
        logger.error("无有效历史数据")
        return

    result = run_backtest(data_dict, BEST_THRESHOLDS)
    print_backtest_result(result)


if __name__ == "__main__":
    main()
