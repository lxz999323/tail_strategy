#!/usr/bin/env python3
"""
基于 baostock 真实数据的 A 股尾盘策略优化（优化版）
=====================================================
使用已缓存数据 + 缩小网格 + 预计算特征，大幅加速。
"""

import os, sys, time, itertools, json
from collections import defaultdict
import numpy as np
import pandas as pd

CACHE_FILE = "baostock_optimize_data.pkl"

# ============================================================
# 1. 加载已缓存的数据
# ============================================================

def load_data():
    """加载已缓存的数据，构建每日快照"""
    if not os.path.exists(CACHE_FILE):
        print(f"错误: 找不到缓存文件 {CACHE_FILE}")
        print("请先运行原始版本下载数据，或手动下载。")
        sys.exit(1)

    data_dict = pd.read_pickle(CACHE_FILE)
    print(f"加载 {len(data_dict)} 支股票数据", flush=True)

    # 构建每日快照（一次性，后续所有回测复用）
    daily_records = defaultdict(list)
    for code, df in data_dict.items():
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            try:
                date = pd.Timestamp(row["日期"]).strftime("%Y-%m-%d")
            except:
                continue
            daily_records[date].append({
                "代码": str(row.get("代码", code.split(".")[-1])),
                "名称": str(row.get("名称", "")),
                "最新价": float(row["收盘"]) if pd.notna(row.get("收盘")) else np.nan,
                "开盘": float(row["开盘"]) if pd.notna(row.get("开盘")) else np.nan,
                "最高": float(row["最高"]) if pd.notna(row.get("最高")) else np.nan,
                "最低": float(row["最低"]) if pd.notna(row.get("最低")) else np.nan,
                "收盘": float(row["收盘"]) if pd.notna(row.get("收盘")) else np.nan,
                "成交量": float(row.get("成交量", 0)) if pd.notna(row.get("成交量")) else 0,
                "成交额": float(row.get("成交额", 0)) if pd.notna(row.get("成交额")) else 0,
                "换手率": float(row["换手率"]) if pd.notna(row.get("换手率")) else 0.0,
                "涨跌幅": float(row["涨跌幅"]) if pd.notna(row.get("涨跌幅")) else 0.0,
                "流通市值": float(row["流通市值"]) if pd.notna(row.get("流通市值")) else np.nan,
            })

    # 转 DataFrame，预计算特征
    print("预计算每日特征...", flush=True)
    daily_snapshots = {}
    for date, records in daily_records.items():
        df = pd.DataFrame(records)
        # 计算特征
        df = _precalc_features(df)
        daily_snapshots[date] = df

    trade_dates = sorted(daily_snapshots.keys())
    print(f"交易日: {len(trade_dates)} 天 ({trade_dates[0]} ~ {trade_dates[-1]})", flush=True)
    return daily_snapshots, trade_dates


def _precalc_features(df):
    """预计算特征，避免每次回测重复计算"""
    df = df.copy()
    # ret_1450 (用涨跌幅近似)
    df["_ret"] = df["涨跌幅"].fillna(0.0)
    # close_position
    price_range = df["最高"].fillna(0) - df["最低"].fillna(0)
    df["_close_pos"] = np.where(price_range > 0, (df["收盘"].fillna(0) - df["最低"].fillna(0)) / price_range, 0.5)
    # turnover_rate
    df["_turn"] = df["换手率"].fillna(0.0)
    # market_cap
    df["_cap"] = df["流通市值"].fillna(0.0)
    return df


# ============================================================
# 2. 回测核心（逐参数组合）
# ============================================================

def run_backtest_fast(daily_snapshots, trade_dates, thresholds,
                      stop_gain=0.03, stop_loss=-0.03, max_positions=5):
    """
    快速回测：使用预计算特征，循环优化。
    输入 thresholds 包含: ret_min, ret_max, close_pos_min, turnover_min, turnover_max, cap_min, cap_max
    """
    ret_min = thresholds.get("ret_min", -999)
    ret_max = thresholds.get("ret_max", 999)
    cp_min = thresholds.get("close_pos_min", 0)
    turn_min = thresholds.get("turnover_min", 0)
    turn_max = thresholds.get("turnover_max", 999)
    cap_min = thresholds.get("market_cap_min", 0)
    cap_max = thresholds.get("market_cap_max", 999999)

    trades = []
    holdings = {}  # code -> {buy_price, buy_date}
    n_dates = len(trade_dates)

    for i, date in enumerate(trade_dates):
        df_today = daily_snapshots[date]

        # ---- 筛选（直接使用预计算列，避免函数调用）----
        mask = (
            (df_today["_ret"] >= ret_min) & (df_today["_ret"] <= ret_max) &
            (df_today["_close_pos"] >= cp_min) &
            (df_today["_turn"] >= turn_min) & (df_today["_turn"] <= turn_max) &
            (df_today["_cap"] >= cap_min) & (df_today["_cap"] <= cap_max)
        )
        selected = df_today[mask]

        # ---- 卖出（T+1）----
        if holdings and i + 1 < n_dates:
            sell_date = trade_dates[i + 1]
            df_next = daily_snapshots[sell_date]
            for code in list(holdings.keys()):
                row = df_next[df_next["代码"] == code]
                if row.empty:
                    continue
                hold = holdings.pop(code)
                buy_p = hold["buy_price"]
                high = row.iloc[0]["最高"] if pd.notna(row.iloc[0]["最高"]) else buy_p
                low = row.iloc[0]["最低"] if pd.notna(row.iloc[0]["最低"]) else buy_p
                close = row.iloc[0]["收盘"] if pd.notna(row.iloc[0]["收盘"]) else buy_p
                high_r = (high - buy_p) / buy_p if buy_p > 0 else -999
                low_r = (low - buy_p) / buy_p if buy_p > 0 else 999
                if high_r >= stop_gain:
                    sell_p = buy_p * (1 + stop_gain)
                elif low_r <= stop_loss:
                    sell_p = buy_p * (1 + stop_loss)
                else:
                    sell_p = close
                ret = (sell_p - buy_p) / buy_p
                trades.append(ret)

        # ---- 买入 ----
        available = max_positions - len(holdings)
        if available > 0 and len(selected) > 0:
            # 过滤已有持仓
            candidates = selected[~selected["代码"].isin(holdings.keys())]
            if len(candidates) > 0:
                # 按涨幅排序，取前 available 支
                candidates = candidates.sort_values("_ret", ascending=False)
                for j in range(min(available, len(candidates))):
                    row = candidates.iloc[j]
                    code = row["代码"]
                    bp = row["收盘"] if pd.notna(row["收盘"]) else 0
                    if bp <= 0:
                        continue
                    holdings[code] = {"buy_price": bp, "buy_date": date}

        # ---- 最后一天强制平仓 ----
        if i == n_dates - 1:
            for code in list(holdings.keys()):
                row = df_today[df_today["代码"] == code]
                if not row.empty:
                    sp = row.iloc[0]["收盘"] if pd.notna(row.iloc[0]["收盘"]) else 0
                    h = holdings.pop(code)
                    ret = (sp - h["buy_price"]) / h["buy_price"] if h["buy_price"] > 0 else 0
                    trades.append(ret)

    n_trades = len(trades)
    if n_trades == 0:
        return {"total_trades": 0, "win_rate": 0, "profit_factor": 0, "total_return": 0}

    returns = np.array(trades)
    win_mask = returns > 0
    n_win = int(win_mask.sum())
    n_lose = n_trades - n_win
    wr = n_win / n_trades
    avg_win = float(returns[win_mask].mean()) if n_win > 0 else 0
    avg_lose = float(returns[~win_mask].mean()) if n_lose > 0 else 0
    pf = abs(avg_win / avg_lose) if avg_lose != 0 else 99.0

    return {
        "total_trades": n_trades,
        "win_trades": n_win,
        "lose_trades": n_lose,
        "win_rate": wr,
        "profit_factor": pf,
        "total_return": float(returns.sum()),
    }


# ============================================================
# 3. 网格搜索（缩小版，聚焦最可能有效的范围）
# ============================================================

PARAM_GRID = {
    "ret_min":        [1.0, 1.5, 2.0],
    "ret_max":        [3.0, 4.0, 5.0],
    "close_pos_min":  [0.6, 0.7, 0.8],
    "turnover_min":   [3.0, 5.0],
    "turnover_max":   [10.0, 15.0, 20.0],
    "market_cap_min": [30, 50],
    "market_cap_max": [100, 150, 200],
}


def run_optimization(daily_snapshots, trade_dates, top_n=10, min_trades=3):
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combos = list(itertools.product(*values))

    # 过滤无效组合
    valid = []
    for combo in combos:
        p = dict(zip(keys, combo))
        if p["ret_min"] >= p["ret_max"]: continue
        if p["turnover_min"] >= p["turnover_max"]: continue
        if p["market_cap_min"] >= p["market_cap_max"]: continue
        valid.append(p)

    print(f"\n网格搜索: {len(valid)} 个组合, {len(trade_dates)} 天", flush=True)
    t0 = time.time()

    results = []
    for idx, params in enumerate(valid, 1):
        bt = run_backtest_fast(daily_snapshots, trade_dates, params)
        if bt["total_trades"] >= min_trades:
            score = bt["win_rate"] * bt["profit_factor"]
            results.append({
                "params": params, "score": score,
                "win_rate": bt["win_rate"], "profit_factor": bt["profit_factor"],
                "total_return": bt["total_return"], "total_trades": bt["total_trades"],
            })
        if idx % 20 == 0:
            print(".", end="", flush=True)
        if idx % 500 == 0:
            el = time.time() - t0
            print(f" [{idx}/{len(valid)}] {el:.0f}s", flush=True)

    el = time.time() - t0
    print(f"\n完成! {len(results)} 组有效, 耗时 {el:.0f}s", flush=True)

    by_score = sorted(results, key=lambda x: x["score"], reverse=True)[:top_n]
    by_return = sorted(results, key=lambda x: x["total_return"], reverse=True)[:top_n]
    by_winrate = sorted(results, key=lambda x: x["win_rate"], reverse=True)[:top_n]

    return {"by_score": by_score, "by_return": by_return, "by_winrate": by_winrate, "all": results}


def print_results(res):
    print(f"\n{'='*100}")
    print(f"  基于 baostock 真实 A 股数据 (124支 × 2022-2023)")
    print(f"{'='*100}")

    for key, title in [
        ("by_score", "综合评分最高 (胜率 x 盈亏比)"),
        ("by_return", "总收益率最高"),
        ("by_winrate", "纯胜率最高"),
    ]:
        items = res[key]
        print(f"\n{'─'*100}")
        print(f"  {title}")
        print(f"{'─'*100}")
        print(f"  {'排名':<4} {'胜率':<8} {'盈亏比':<8} {'评分':<8} {'总收益率':<10} {'交易':<6}  参数")
        print(f"  {'─'*90}")
        for i, r in enumerate(items, 1):
            p = r["params"]
            ps = (f"涨幅={p['ret_min']}~{p['ret_max']}% "
                  f"收盘位>={p['close_pos_min']} "
                  f"换手={p['turnover_min']}~{p['turnover_max']}% "
                  f"市值={p['market_cap_min']}~{p['market_cap_max']}亿")
            print(f"  {i:<4} {r['win_rate']*100:<8.1f} {r['profit_factor']:<8.2f} "
                  f"{r['score']:<8.4f} {r['total_return']*100:<+9.2f}% "
                  f"{r['total_trades']:<6} {ps}", flush=True)


# ============================================================
# 主流程
# ============================================================

if __name__ == "__main__":
    daily_snapshots, trade_dates = load_data()
    results = run_optimization(daily_snapshots, trade_dates, top_n=10, min_trades=3)
    print_results(results)

    # 顶部分析
    for name, key in [("综合评分", "by_score"), ("收益率", "by_return"), ("胜率", "by_winrate")]:
        best = results[key][0]
        print(f"\n  [{name}最优] 胜率={best['win_rate']*100:.1f}% "
              f"盈亏比={best['profit_factor']:.2f} "
              f"收益率={best['total_return']*100:+.2f}% "
              f"交易={best['total_trades']}次 "
              f"参数={best['params']}")

    print(f"\n{'='*100}")
    print(f"  最终推荐策略（综合评分最优）:")
    best = results["by_score"][0]
    p = best["params"]
    print(f"  - 尾盘涨幅: {p['ret_min']}% ~ {p['ret_max']}%")
    print(f"  - 收盘位置: >= {p['close_pos_min']}")
    print(f"  - 换手率: {p['turnover_min']}% ~ {p['turnover_max']}%")
    print(f"  - 流通市值: {p['market_cap_min']}亿 ~ {p['market_cap_max']}亿")
    print(f"  - 预期胜率: {best['win_rate']*100:.1f}%")
    print(f"  - 预期盈亏比: {best['profit_factor']:.2f}")
    print(f"  - 总收益率(2年): {best['total_return']*100:+.2f}%")
    print(f"  - 样本交易次数: {best['total_trades']} 次")
    print(f"{'='*100}")
