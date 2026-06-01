#!/usr/bin/env python3
"""
生成 dashboard_data.json — 将每日选股结果导出为网页可读的格式。

用法：
    # 先跑选股程序，再导出数据
    python run_daily_pick.py --dry-run
    python update_dashboard.py

    # 然后刷新 dashboard.html 即可看到实时结果
"""

import os
import json
import sys
from datetime import datetime

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import logger
from src.daily_picker import daily_pick
from config.settings import (
    TOTAL_CAPITAL, BACKTEST_WIN_RATE, BACKTEST_PROFIT_FACTOR,
)


def export_dashboard():
    """运行每日选股并将结果导出为 dashboard_data.json"""

    print("=" * 50)
    print("  导出选股结果到 dashboard_data.json")
    print("=" * 50)

    # 1. 执行选股
    df = daily_pick(
        win_rate=BACKTEST_WIN_RATE,
        profit_factor=BACKTEST_PROFIT_FACTOR,
    )

    # 2. 构造 JSON 数据
    now = datetime.now()
    is_trade_day = now.weekday() < 5

    data = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "isTradingDay": is_trade_day,
        "isOverheated": False,
        "stocks": [],
    }

    if df.empty:
        # 判断是否过热（检查候选数量）
        from src.data_fetcher import get_realtime_quotes
        from src.feature_engine import calc_features, filter_by_thresholds
        from config.settings import BEST_THRESHOLDS, OVERHEAT_LIMIT

        try:
            quotes = get_realtime_quotes()
            feat = calc_features(quotes)
            selected = filter_by_thresholds(feat, BEST_THRESHOLDS)
            if len(selected) > OVERHEAT_LIMIT:
                data["isOverheated"] = True
        except:
            pass

        # 空仓，不添加股票
        pass
    else:
        for _, row in df.iterrows():
            s = {
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "price": float(row.get("最新价", 0)),
                "ret": float(row.get("ret_1450", 0)),
                "closePos": float(row.get("close_position", 0)),
                "volRatio": float(row.get("volume_ratio", 1.0)),
                "turnover": float(row.get("turnover_rate", 0)),
                "marketCap": float(row.get("market_cap", 0)),
                "buyAmount": float(row.get("capped_amount", 0)),
            }
            data["stocks"].append(s)

    # 3. 写入 JSON
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    stock_count = len(data["stocks"])
    if stock_count > 0:
        total_amount = sum(s["buyAmount"] for s in data["stocks"])
        print(f"\n  ✅ 已导出 {stock_count} 支股票")
        print(f"  💰 建议总金额: {total_amount / 10000:.1f} 万元")
    else:
        reason = "市场过热" if data["isOverheated"] else "无符合条件的股票"
        print(f"\n  🛌 今日空仓: {reason}")

    print(f"  📁 文件: {output_path}")
    print(f"  🌐 请刷新 dashboard.html 查看结果")
    print()


if __name__ == "__main__":
    export_dashboard()
