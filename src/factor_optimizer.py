"""
因子优化模块
============
通过网格搜索遍历因子参数组合，按「胜率 x 盈亏比」评分排序，输出 Top N。
"""

import os
import itertools
import time
import re
import pandas as pd
from src.utils import logger
from src.backtest_engine import run_backtest, print_backtest_result
from config.settings import BEST_THRESHOLDS, BACKTEST_START, BACKTEST_END


PARAM_GRID = {
    "ret_min": [1.0, 1.5, 2.0, 2.5],
    "ret_max": [3.0, 4.0, 5.0, 6.0],
    "volume_ratio_min": [1.0, 1.2, 1.5, 2.0],
    "close_pos_min": [0.6, 0.7, 0.8],
    "turnover_min": [3.0, 5.0, 8.0],
    "turnover_max": [10.0, 15.0, 20.0],
    "market_cap_min": [30, 50, 80],
    "market_cap_max": [100, 150, 200],
}


def generate_param_combinations(param_grid: dict = None) -> list:
    """生成所有参数组合的笛卡尔积，跳过无效组合。"""
    if param_grid is None:
        param_grid = PARAM_GRID
    keys = param_grid.keys()
    values = param_grid.values()
    combos = list(itertools.product(*values))
    result = []
    for combo in combos:
        p = dict(zip(keys, combo))
        if p.get("ret_min", 0) >= p.get("ret_max", 999): continue
        if p.get("turnover_min", 0) >= p.get("turnover_max", 999): continue
        if p.get("market_cap_min", 0) >= p.get("market_cap_max", 999): continue
        result.append(p)
    return result


def grid_search_optimize(data_dict: dict, param_grid: dict = None, top_n: int = 5, min_trades: int = 10) -> list:
    """
    网格搜索最优因子参数组合。
    按「胜率 x 盈亏比」评分排序。

    Returns:
        评分最高的 top_n 组参数列表
    """
    if param_grid is None:
        param_grid = PARAM_GRID
    combos = generate_param_combinations(param_grid)
    total = len(combos)
    logger.info("=" * 60)
    logger.info("因子网格搜索启动 | 参数组合: %d | 最少交易: %d", total, min_trades)
    logger.info("=" * 60)

    results = []
    start_time = time.time()

    for idx, params in enumerate(combos, 1):
        try:
            bt = run_backtest(data_dict, params)
            if bt["total_trades"] < min_trades:
                continue
            score = bt["win_rate"] * bt["profit_factor"]
            results.append({
                "params": params, "score": score,
                "win_rate": bt["win_rate"], "profit_factor": bt["profit_factor"],
                "total_trades": bt["total_trades"], "total_return": bt["total_return"],
            })
            elapsed = time.time() - start_time
            logger.info("[%3d/%d] 评分: %.4f | 胜率: %.2f%% | 盈亏比: %.2f | 交易: %d | %.1fs",
                        idx, total, score, bt["win_rate"]*100, bt["profit_factor"], bt["total_trades"], elapsed)
        except Exception as e:
            logger.warning("[%3d/%d] 异常: %s", idx, total, e)

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("网格搜索完成，有效结果: %d", len(results))
    return results[:top_n]


def print_top_results(top_results: list):
    """打印 Top N 最优参数。"""
    print("\n" + "=" * 70)
    print("  Top 最优参数组合")
    print("=" * 70)
    for i, r in enumerate(top_results, 1):
        p = r["params"]
        print(f"\n  [{i}] 评分: {r['score']:.4f}")
        print(f"      ret_min={p['ret_min']}, ret_max={p['ret_max']}")
        print(f"      volume_ratio_min={p['volume_ratio_min']}")
        print(f"      close_pos_min={p['close_pos_min']}")
        print(f"      turnover_min={p['turnover_min']}, turnover_max={p['turnover_max']}")
        print(f"      market_cap_min={p['market_cap_min']}, market_cap_max={p['market_cap_max']}")
        print(f"      胜率={r['win_rate']*100:.2f}% | 盈亏比={r['profit_factor']:.2f} | "
              f"交易={r['total_trades']} | 收益={r['total_return']*100:+.2f}%")
    print("\n" + "=" * 70)


def update_settings_best(result: dict, settings_path: str = None):
    """将最优参数写入 config/settings.py。"""
    if settings_path is None:
        settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.py")
    params = result["params"]

    with open(settings_path, "r", encoding="utf-8") as f:
        content = f.read()

    threshold_lines = "BEST_THRESHOLDS = {\n"
    for key in ["ret_min", "ret_max", "volume_ratio_min", "close_pos_min",
                 "turnover_min", "turnover_max", "market_cap_min", "market_cap_max"]:
        val = params.get(key, BEST_THRESHOLDS.get(key, 0))
        val_str = f"{val:.1f}" if isinstance(val, float) else str(val)
        threshold_lines += f'    "{key}": {val_str},\n'
    threshold_lines += "}"

    pattern = r"BEST_THRESHOLDS\s*=\s*\{[^}]+\}"
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, threshold_lines, content, flags=re.DOTALL)

    content = re.sub(r"BACKTEST_WIN_RATE\s*=\s*[\d.]+", f"BACKTEST_WIN_RATE = {result['win_rate']:.4f}", content)
    content = re.sub(r"BACKTEST_PROFIT_FACTOR\s*=\s*[\d.]+", f"BACKTEST_PROFIT_FACTOR = {result['profit_factor']:.4f}", content)

    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("已将最优参数更新到 %s", settings_path)
    logger.info("  BACKTEST_WIN_RATE = %.4f", result['win_rate'])
    logger.info("  BACKTEST_PROFIT_FACTOR = %.4f", result['profit_factor'])
