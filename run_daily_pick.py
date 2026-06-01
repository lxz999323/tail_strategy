#!/usr/bin/env python3
"""
A股尾盘买入策略 - 每日选股入口
=================================
用法: python run_daily_pick.py
      python run_daily_pick.py --dry-run
      python run_daily_pick.py --no-email
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import logger
from src.daily_picker import daily_pick, format_pick_result
from src.email_sender import send_html_report
from config.settings import TOTAL_CAPITAL, BACKTEST_WIN_RATE, BACKTEST_PROFIT_FACTOR, EMAIL_TO


def main():
    parser = argparse.ArgumentParser(description="每日选股")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不发送邮件")
    parser.add_argument("--no-email", action="store_true", help="不发送邮件")
    parser.add_argument("--to", nargs="+", default=None, help="收件人邮箱")
    args = parser.parse_args()

    logger.info("每日选股启动 (dry_run=%s)", args.dry_run)

    df_result = daily_pick(win_rate=BACKTEST_WIN_RATE, profit_factor=BACKTEST_PROFIT_FACTOR)
    print("\n" + format_pick_result(df_result) + "\n")

    if args.dry_run or args.no_email:
        logger.info("试运行模式，不发送邮件")
        return

    to_list = args.to if args.to else EMAIL_TO
    success = send_html_report(df_result, TOTAL_CAPITAL, to_emails=to_list)
    if success:
        logger.info("全部流程完成")
    else:
        logger.warning("邮件发送失败，结果已打印到控制台")


if __name__ == "__main__":
    main()
