"""
特征工程模块
============
根据实时行情数据计算尾盘特征因子，并按阈值筛选股票。
"""

import pandas as pd
import numpy as np
from typing import Optional
from src.utils import logger


def calc_features(df_quote: pd.DataFrame) -> pd.DataFrame:
    """
    根据实时行情 DataFrame 计算每支股票的尾盘特征因子。

    计算的特征：
    - ret_1450:      现价相对开盘价涨幅（%）
    - volume_ratio:  量比
    - close_position: (现价-最低)/(最高-最低)，0~1
    - turnover_rate: 换手率（%）
    - market_cap:    流通市值（亿元）
    - above_ma20:    是否在 20 日均线上方

    Args:
        df_quote: 实时行情 DataFrame

    Returns:
        新增特征列后的 DataFrame
    """
    df = df_quote.copy()

    # 1. 尾盘涨幅 ret_1450
    if "开盘" in df.columns and "最新价" in df.columns:
        df["ret_1450"] = ((df["最新价"] - df["开盘"]) / df["开盘"].replace(0, np.nan)) * 100
    else:
        df["ret_1450"] = df.get("涨跌幅", 0.0)

    # 2. 量比 volume_ratio
    if "量比" in df.columns:
        df["volume_ratio"] = df["量比"]
    else:
        logger.warning("数据源无「量比」字段，使用默认值 1.0")
        df["volume_ratio"] = 1.0

    # 3. 收盘位置 close_position
    if all(c in df.columns for c in ["最高", "最低", "最新价"]):
        price_range = df["最高"] - df["最低"]
        df["close_position"] = np.where(price_range > 0, (df["最新价"] - df["最低"]) / price_range, 1.0)
    else:
        df["close_position"] = 0.5

    # 4. 换手率 turnover_rate
    df["turnover_rate"] = df.get("换手率", 0.0)

    # 5. 流通市值 market_cap（亿元）
    if "流通市值" in df.columns:
        df["market_cap"] = df["流通市值"] / 1e8
    else:
        df["market_cap"] = 0.0

    # 6. MA20（简化，默认不过滤）
    df["above_ma20"] = True

    df = df.replace([np.inf, -np.inf], np.nan)

    logger.info("特征计算完成，共 %d 支股票", len(df))
    return df


def filter_by_thresholds(df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """
    按给定的因子阈值筛选股票。

    Args:
        df: 包含特征列的 DataFrame
        thresholds: 阈值字典，支持 ret_min/ret_max、volume_ratio_min、
                    close_pos_min、turnover_min/turnover_max、
                    market_cap_min/market_cap_max

    Returns:
        筛选后的 DataFrame
    """
    df_filtered = df.copy()
    conditions = []

    if "ret_min" in thresholds:
        conditions.append(df_filtered["ret_1450"] >= thresholds["ret_min"])
    if "ret_max" in thresholds:
        conditions.append(df_filtered["ret_1450"] <= thresholds["ret_max"])
    if "volume_ratio_min" in thresholds:
        conditions.append(df_filtered["volume_ratio"] >= thresholds["volume_ratio_min"])
    if "close_pos_min" in thresholds:
        conditions.append(df_filtered["close_position"] >= thresholds["close_pos_min"])
    if "turnover_min" in thresholds:
        conditions.append(df_filtered["turnover_rate"] >= thresholds["turnover_min"])
    if "turnover_max" in thresholds:
        conditions.append(df_filtered["turnover_rate"] <= thresholds["turnover_max"])
    if "market_cap_min" in thresholds:
        conditions.append(df_filtered["market_cap"] >= thresholds["market_cap_min"])
    if "market_cap_max" in thresholds:
        conditions.append(df_filtered["market_cap"] <= thresholds["market_cap_max"])

    if conditions:
        combined = conditions[0]
        for cond in conditions[1:]:
            combined = combined & cond
        df_filtered = df_filtered.loc[combined].copy()

    df_filtered = df_filtered.dropna(subset=["ret_1450", "volume_ratio", "close_position"])

    logger.info("阈值筛选: %d -> %d 支股票", len(df), len(df_filtered))
    return df_filtered
