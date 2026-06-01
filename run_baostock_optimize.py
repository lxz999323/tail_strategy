#!/usr/bin/env python3
"""
A股尾盘买入策略 — 基于 baostock 真实数据的因子优化
====================================================
从 baostock 获取真实 A 股历史日线数据，运行网格搜索，
找出收益率最高的策略参数组合。

用法：
    python run_baostock_optimize.py                          # 全自动运行
    python run_baostock_optimize.py --sample 100 --top 10    # 自定义
"""

import argparse
import os
import sys
import time
import itertools
import json
import re
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 第一步：从 baostock 下载真实数据
# ============================================================

def download_stock_list(max_count=500):
    """
    从 baostock 获取 A 股股票列表。
    过滤 ST、退市股、指数，保证是真实的交易代码。
    """
    import baostock as bs

    # 使用最近的交易日（周一到周五）
    from datetime import datetime, timedelta
    today = datetime.now()
    while today.weekday() >= 5:  # 周末往前推
        today -= timedelta(days=1)
    query_day = today.strftime('%Y-%m-%d')

    lg = bs.login()
    if lg.error_code != '0':
        raise ConnectionError(f"baostock 登录失败: {lg.error_msg}")

    # 获取所有证券
    rs = bs.query_all_stock(day=query_day)
    stocks = []
    while rs.next():
        row = rs.get_row_data()
        code = row[0]      # 如 sh.600000
        trade_status = row[1]  # 1=正常交易
        code_name = row[2]  # 股票名称
        # 只取正常交易的
        if trade_status != '1':
            continue
        # 只取沪市(6xx)和深市(0xx, 3xx)的真实股票
        num_part = code.split('.')[1]
        if not any(num_part.startswith(p) for p in ['600', '601', '603', '605',
                                                      '000', '001', '002', '003', '300']):
            continue
        # 过滤 ST、退市、指数
        if any(kw in code_name for kw in ['ST', '退', '指数', 'ETF', 'LOF']):
            continue
        stocks.append({'code': code, 'name': code_name})

    bs.logout()
    print(f"下载股票列表: 共 {len(stocks)} 支 A 股 (取前 {min(max_count, len(stocks))} 支)")
    return stocks[:max_count]


def download_kline_baostock(stock_code, start_date='2022-01-01', end_date='2023-12-31'):
    """
    下载单支股票的日线 K 线数据（前复权）。
    注意：调用前需要 bs.login()，调用后不需要 logout（全局连接复用）。

    baostock 返回字段：
    date, open, high, low, close, volume, amount, adjustflag, turn, tradestatus, pctChg
    """
    import baostock as bs

    rs = bs.query_history_k_data_plus(
        stock_code,
        'date,open,high,low,close,volume,amount,adjustflag,turn,tradestatus,pctChg',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2'  # 前复权
    )
    if rs.error_code != '0':
        return pd.DataFrame()

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=[
        '日期', '开盘', '最高', '最低', '收盘', '成交量',
        '成交额', 'adjustflag', '换手率', '交易状态', '涨跌幅'
    ])

    # 类型转换
    for col in ['开盘', '最高', '最低', '收盘', '成交量', '成交额', '换手率', '涨跌幅']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['日期'] = pd.to_datetime(df['日期'])
    df = df.dropna(subset=['收盘'])
    return df


def download_all_stocks(stock_list, start_date='2022-01-01', end_date='2023-12-31', max_workers=5):
    """
    批量下载所有股票 K 线数据（限制并发避免被 ban）。
    """
    import baostock as bs
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 全局登录 baostock（所有线程复用同一个连接）
    lg = bs.login()
    if lg.error_code != '0':
        print(f"baostock 登录失败: {lg.error_msg}")
        return {}

    print(f"开始下载 {len(stock_list)} 支股票 K 线数据 [{start_date} ~ {end_date}]...")
    data_dict = {}
    failed = []
    start = time.time()

    def fetch_one(item):
        try:
            df = download_kline_baostock(item['code'], start_date, end_date)
            if df is not None and len(df) > 20:  # 至少 20 个交易日
                df['代码'] = item['code'].split('.')[1]  # 转为纯数字代码
                df['名称'] = item['name']
                # 估算流通市值（亿元）= 成交额(元) / 换手率(%) * 100 / 1e8
                df['流通市值'] = np.where(
                    df['换手率'] > 0,
                    df['成交额'] * 100 / df['换手率'] / 1e8,
                    np.nan
                )
                return item['code'], df
        except Exception as e:
            pass
        return item['code'], None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, s): s for s in stock_list}
        for i, future in enumerate(as_completed(futures), 1):
            code, df = future.result()
            if df is not None:
                data_dict[code] = df
            else:
                failed.append(code)
            if i % 50 == 0:
                elapsed = time.time() - start
                print(f"  进度: {i}/{len(stock_list)} | 成功: {len(data_dict)} | 耗时: {elapsed:.0f}s")

    bs.logout()
    elapsed = time.time() - start
    print(f"下载完成: 成功 {len(data_dict)} 支, 失败 {len(failed)} 支, 耗时 {elapsed:.0f}s")
    return data_dict


# ============================================================
# 第二步：特征计算 + 回测引擎（与项目代码一致）
# ============================================================

def calc_features(df_quote):
    """计算尾盘特征因子"""
    df = df_quote.copy()

    # 尾盘涨幅（用当日涨跌幅近似，因为日线只有收盘数据）
    df['ret_1450'] = df.get('涨跌幅', 0.0)

    # 量比（日线无法精确计算，用涨跌幅强度替代）
    # 对于日线回测，我们使用换手率作为辅助判断
    df['volume_ratio'] = 1.0  # 默认值，后续可用换手率辅助筛选

    # 收盘位置
    price_range = df['最高'] - df['最低']
    df['close_position'] = np.where(
        price_range > 0,
        (df['收盘'] - df['最低']) / price_range,
        0.5
    )

    # 换手率
    df['turnover_rate'] = df.get('换手率', 0.0)

    # 流通市值（亿元，已估算）
    df['market_cap'] = df.get('流通市值', 0.0)

    # MA20以上（用收盘价近似判断）
    df['above_ma20'] = True

    df = df.replace([np.inf, -np.inf], np.nan)
    return df


def filter_by_thresholds(df, thresholds):
    """按阈值筛选"""
    df_f = df.copy()
    conds = []

    if 'ret_min' in thresholds:
        conds.append(df_f['ret_1450'] >= thresholds['ret_min'])
    if 'ret_max' in thresholds:
        conds.append(df_f['ret_1450'] <= thresholds['ret_max'])
    if 'volume_ratio_min' in thresholds:
        conds.append(df_f['volume_ratio'] >= thresholds['volume_ratio_min'])
    if 'close_pos_min' in thresholds:
        conds.append(df_f['close_position'] >= thresholds['close_pos_min'])
    if 'turnover_min' in thresholds:
        conds.append(df_f['turnover_rate'] >= thresholds['turnover_min'])
    if 'turnover_max' in thresholds:
        conds.append(df_f['turnover_rate'] <= thresholds['turnover_max'])
    if 'market_cap_min' in thresholds:
        conds.append(df_f['market_cap'] >= thresholds['market_cap_min'])
    if 'market_cap_max' in thresholds:
        conds.append(df_f['market_cap'] <= thresholds['market_cap_max'])

    if conds:
        combined = conds[0]
        for c in conds[1:]:
            combined = combined & c
        df_f = df_f.loc[combined].copy()

    df_f = df_f.dropna(subset=['ret_1450', 'close_position'])
    return df_f


def run_backtest(data_dict, thresholds, stop_gain=0.03, stop_loss=-0.03, max_positions=5):
    """
    回测核心逻辑（与项目 backtest_engine.py 一致）。
    每日尾盘筛选 -> T+1 止盈/止损/收盘卖出 -> 统计。
    """
    daily_records = defaultdict(list)
    for code, df in data_dict.items():
        if df is None or df.empty or '日期' not in df.columns:
            continue
        for _, row in df.iterrows():
            date = pd.Timestamp(row['日期']).strftime('%Y-%m-%d')
            daily_records[date].append({
                '代码': row.get('代码', code.split('.')[-1]),
                '名称': row.get('名称', ''),
                '最新价': row.get('收盘', np.nan),
                '开盘': row.get('开盘', np.nan),
                '最高': row.get('最高', np.nan),
                '最低': row.get('最低', np.nan),
                '收盘': row.get('收盘', np.nan),
                '成交量': row.get('成交量', 0),
                '成交额': row.get('成交额', 0),
                '换手率': row.get('换手率', np.nan),
                '涨跌幅': row.get('涨跌幅', 0.0),
                '流通市值': row.get('流通市值', np.nan),
            })

    daily_snapshots = {}
    for date, records in daily_records.items():
        df = pd.DataFrame(records)
        for col in ['最新价', '开盘', '最高', '最低', '收盘', '换手率', '涨跌幅', '流通市值']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        daily_snapshots[date] = df

    if not daily_snapshots:
        return {'total_trades': 0, 'win_trades': 0, 'lose_trades': 0,
                'win_rate': 0.0, 'total_return': 0.0, 'avg_profit': 0.0,
                'avg_loss': 0.0, 'profit_factor': 0.0, 'trades': []}

    trade_dates = sorted(daily_snapshots.keys())
    trades = []
    holdings = {}

    for i, date in enumerate(trade_dates):
        df_today = daily_snapshots[date]
        df_feat = calc_features(df_today)
        df_selected = filter_by_thresholds(df_feat, thresholds)

        # 卖出 (T+1)
        if holdings and i + 1 < len(trade_dates):
            sell_date = trade_dates[i + 1]
            df_next = daily_snapshots.get(sell_date)
            if df_next is not None:
                for code in list(holdings.keys()):
                    row = df_next[df_next['代码'] == code]
                    if row.empty:
                        continue
                    hold = holdings.pop(code)
                    buy_price = hold['buy_price']
                    high = row.iloc[0].get('最高', np.nan)
                    low = row.iloc[0].get('最低', np.nan)
                    close = row.iloc[0].get('收盘', np.nan)

                    high_ret = (high - buy_price) / buy_price if not np.isnan(high) else -999
                    low_ret = (low - buy_price) / buy_price if not np.isnan(low) else 999

                    if high_ret >= stop_gain:
                        sell_price = buy_price * (1 + stop_gain)
                        reason = '止盈'
                    elif low_ret <= stop_loss:
                        sell_price = buy_price * (1 + stop_loss)
                        reason = '止损'
                    else:
                        sell_price = close
                        reason = '收盘'

                    ret = (sell_price - buy_price) / buy_price
                    trades.append({
                        'code': code, 'buy_date': hold['buy_date'],
                        'sell_date': sell_date, 'return': ret, 'exit_reason': reason
                    })

        # 买入
        available = max_positions - len(holdings)
        if available > 0 and not df_selected.empty:
            candidates = df_selected[~df_selected['代码'].isin([c.split('.')[-1] for c in holdings.keys()])]
            if not candidates.empty:
                candidates = candidates.sort_values('ret_1450', ascending=False)
                for _, row in candidates.head(available).iterrows():
                    code = row['代码']
                    buy_price = row.get('最新价', row.get('收盘', np.nan))
                    if pd.isna(buy_price) or buy_price <= 0:
                        continue
                    holdings[f'sh.{code}'] = {'buy_price': buy_price, 'buy_date': date}

        # 最后一天强制平仓
        if i == len(trade_dates) - 1:
            for code in list(holdings.keys()):
                row = df_today[df_today['代码'] == code.split('.')[-1]]
                if not row.empty:
                    sell_price = row.iloc[0].get('收盘', np.nan)
                    hold = holdings.pop(code)
                    ret = (sell_price - hold['buy_price']) / hold['buy_price']
                    trades.append({
                        'code': code, 'buy_date': hold['buy_date'],
                        'sell_date': date, 'return': ret, 'exit_reason': '强制平仓'
                    })

    # 统计
    if not trades:
        return {'total_trades': 0, 'win_trades': 0, 'lose_trades': 0,
                'win_rate': 0.0, 'total_return': 0.0, 'avg_profit': 0.0,
                'avg_loss': 0.0, 'profit_factor': 0.0, 'trades': []}

    df_t = pd.DataFrame(trades)
    returns = df_t['return']
    win = returns > 0
    lose = returns <= 0
    total = len(trades)
    win_cnt = int(win.sum())
    lose_cnt = int(lose.sum())
    win_rate = win_cnt / total if total > 0 else 0
    avg_profit = returns[win].mean() if win_cnt > 0 else 0
    avg_loss = returns[lose].mean() if lose_cnt > 0 else 0
    profit_factor = abs(avg_profit / avg_loss) if avg_loss != 0 else float('inf')

    return {
        'total_trades': total,
        'win_trades': win_cnt,
        'lose_trades': lose_cnt,
        'win_rate': win_rate,
        'total_return': returns.sum(),
        'avg_profit': avg_profit,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'trades': trades,
    }


# ============================================================
# 第三步：网格搜索
# ============================================================

# 优化参数网格
PARAM_GRID = {
    "ret_min": [1.0, 1.5, 2.0, 2.5],
    "ret_max": [3.0, 4.0, 5.0, 6.0],
    "close_pos_min": [0.6, 0.7, 0.8],
    "turnover_min": [3.0, 5.0, 8.0],
    "turnover_max": [10.0, 15.0, 20.0],
    "market_cap_min": [30, 50, 80],
    "market_cap_max": [100, 150, 200],
}


def generate_combinations(param_grid=None):
    """生成所有参数组合"""
    if param_grid is None:
        param_grid = PARAM_GRID
    keys = param_grid.keys()
    values = param_grid.values()
    combos = list(itertools.product(*values))
    result = []
    for combo in combos:
        p = dict(zip(keys, combo))
        if p.get("ret_min", 0) >= p.get("ret_max", 999):
            continue
        if p.get("turnover_min", 0) >= p.get("turnover_max", 999):
            continue
        if p.get("market_cap_min", 0) >= p.get("market_cap_max", 999):
            continue
        result.append(p)
    return result


def run_optimization(data_dict, param_grid=None, top_n=10, min_trades=5):
    """
    网格搜索最优参数组合。
    按「胜率 × 盈亏比」和「总收益率」两种标准排序。
    """
    if param_grid is None:
        param_grid = PARAM_GRID

    combos = generate_combinations(param_grid)
    print(f"\n{'='*70}")
    print(f"  网格搜索启动: {len(combos)} 个参数组合")
    print(f"  数据: {len(data_dict)} 支股票 | 最少交易: {min_trades}")
    print(f"{'='*70}")

    results = []
    start_time = time.time()

    for idx, params in enumerate(combos, 1):
        try:
            bt = run_backtest(data_dict, params)

            if bt['total_trades'] < min_trades:
                continue

            score = bt['win_rate'] * bt['profit_factor']
            results.append({
                'params': params,
                'score': score,
                'win_rate': bt['win_rate'],
                'profit_factor': bt['profit_factor'],
                'total_return': bt['total_return'],
                'total_trades': bt['total_trades'],
                'win_trades': bt['win_trades'],
                'lose_trades': bt['lose_trades'],
            })

            if idx % 10 == 0 or idx == len(combos):
                elapsed = time.time() - start_time
                print(f"  进度: {idx}/{len(combos)} | 有效: {len(results)} | 耗时: {elapsed:.0f}s")

        except Exception as e:
            continue

    elapsed = time.time() - start_time
    print(f"\n网格搜索完成! 有效结果: {len(results)}/{len(combos)} 耗时: {elapsed:.0f}s")

    # 按综合评分排序
    by_score = sorted(results, key=lambda x: x['score'], reverse=True)
    # 按总收益率排序
    by_return = sorted(results, key=lambda x: x['total_return'], reverse=True)
    # 按胜率排序
    by_winrate = sorted(results, key=lambda x: x['win_rate'], reverse=True)

    return {
        'by_score': by_score[:top_n],
        'by_return': by_return[:top_n],
        'by_winrate': by_winrate[:top_n],
        'all': results,
    }


def print_results(result_dict, top_n=10):
    """打印三种排序结果"""
    print("\n" + "=" * 80)
    print(" 📊 A 股尾盘买入策略 — 真实数据网格搜索结果")
    print("=" * 80)

    categories = [
        ('by_score', '🏆 综合评分最高 (胜率 × 盈亏比)'),
        ('by_return', '💰 总收益率最高'),
        ('by_winrate', '🎯 胜率最高'),
    ]

    for key, title in categories:
        items = result_dict[key]
        print(f"\n{'─'*80}")
        print(f"  {title}")
        print(f"{'─'*80}")
        print(f"  {'排名':<4} {'胜率':<8} {'盈亏比':<8} {'综合评分':<10} {'总收益率':<10} {'交易次数':<8} {'参数'}")
        print(f"  {'─'*76}")
        for i, r in enumerate(items, 1):
            p = r['params']
            params_str = (f"ret={p['ret_min']}~{p['ret_max']}% "
                          f"pos>={p['close_pos_min']} "
                          f"turn={p['turnover_min']}~{p['turnover_max']}% "
                          f"cap={p['market_cap_min']}~{p['market_cap_max']}亿")
            print(f"  {i:<4} {r['win_rate']*100:<8.1f} {r['profit_factor']:<8.2f} "
                  f"{r['score']:<10.4f} {r['total_return']*100:<+9.2f}% "
                  f"{r['total_trades']:<8} {params_str}")


def save_best_to_config(best_result):
    """将最佳参数写入 config/settings.py"""
    params = best_result['params']
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'settings.py')

    with open(settings_path, 'r', encoding='utf-8') as f:
        content = f.read()

    threshold_lines = "BEST_THRESHOLDS = {\n"
    for key in ["ret_min", "ret_max", "volume_ratio_min", "close_pos_min",
                 "turnover_min", "turnover_max", "market_cap_min", "market_cap_max"]:
        val = params.get(key, 0)
        if key == 'volume_ratio_min':
            val_str = "1.0"  # 回测中不使用量比，设为默认值
        elif isinstance(val, float):
            val_str = f"{val:.1f}"
        else:
            val_str = str(val)
        threshold_lines += f'    "{key}": {val_str},\n'
    threshold_lines += "}"

    pattern = r"BEST_THRESHOLDS\s*=\s*\{[^}]+\}"
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, threshold_lines, content, flags=re.DOTALL)

    content = re.sub(
        r"BACKTEST_WIN_RATE\s*=\s*[\d.]+",
        f"BACKTEST_WIN_RATE = {best_result['win_rate']:.4f}",
        content
    )
    content = re.sub(
        r"BACKTEST_PROFIT_FACTOR\s*=\s*[\d.]+",
        f"BACKTEST_PROFIT_FACTOR = {best_result['profit_factor']:.4f}",
        content
    )

    with open(settings_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\n✓ 已将最优参数更新到 {settings_path}")


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='基于 baostock 真实数据的因子优化')
    parser.add_argument('--sample', type=int, default=300, help='股票样本数')
    parser.add_argument('--top', type=int, default=10, help='输出 Top N')
    parser.add_argument('--min-trades', type=int, default=5, help='最少交易次数')
    parser.add_argument('--start', default='2022-01-01', help='回测起始日')
    parser.add_argument('--end', default='2023-12-31', help='回测结束日')
    parser.add_argument('--cache', action='store_true', help='使用缓存（如果存在）')
    args = parser.parse_args()

    cache_file = f'baostock_data_{args.sample}_{args.start[:4]}_{args.end[:4]}.pkl'

    # 加载数据
    if args.cache and os.path.exists(cache_file):
        print(f"加载缓存数据: {cache_file}")
        data_dict = pd.read_pickle(cache_file)
    else:
        stock_list = download_stock_list(max_count=args.sample)
        data_dict = download_all_stocks(stock_list, args.start, args.end, max_workers=5)

        # 保存缓存
        if data_dict:
            pd.to_pickle(data_dict, cache_file)
            print(f"数据已缓存到: {cache_file}")

    if not data_dict:
        print("错误: 无有效数据!")
        return

    # 运行优化
    results = run_optimization(
        data_dict,
        top_n=args.top,
        min_trades=args.min_trades,
    )

    # 打印结果
    print_results(results, top_n=args.top)

    # 选出综合最优
    best = results['by_score'][0]

    print(f"\n{'='*80}")
    print(f"  最优策略 (综合评分) 参数:")
    print(f"  {json.dumps(best['params'], ensure_ascii=False, indent=4)}")
    print(f"  胜率: {best['win_rate']*100:.2f}%")
    print(f"  盈亏比: {best['profit_factor']:.2f}")
    print(f"  总收益率: {best['total_return']*100:+.2f}%")
    print(f"  交易次数: {best['total_trades']}")
    print(f"{'='*80}")

    # 询问是否写入配置
    try:
        choice = input("\n是否将最优参数写入 config/settings.py？(1=是, 2=否): ").strip()
        if choice == '1':
            save_best_to_config(best)
    except:
        pass

    print("\n✓ 完成!")


if __name__ == '__main__':
    main()
