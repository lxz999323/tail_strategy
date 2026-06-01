"""
数据获取模块
============
使用 akshare 获取 A 股实时行情和历史日线数据。
所有网络请求均包含重试机制。
"""

import time
from typing import Optional
import pandas as pd
import numpy as np
from src.utils import logger, retry
from config.settings import TAIL_SNAPSHOT_TIME, MAX_RETRY_TIMES


INDEX_CODES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "科创50": "000688",
}


@retry(max_times=MAX_RETRY_TIMES, delay=2.0)
def get_realtime_quotes() -> pd.DataFrame:
    """
    获取 A 股全市场实时行情（akshare stock_zh_a_spot_em）。

    Returns:
        DataFrame，包含：代码、名称、最新价、涨跌幅、成交量、成交额、
        换手率、流通市值、最高、最低、开盘、量比
    """
    import akshare as ak

    logger.info("正在获取 A 股实时行情...")
    df = ak.stock_zh_a_spot_em()

    column_map = {
        "代码": "代码", "名称": "名称", "最新价": "最新价",
        "涨跌幅": "涨跌幅", "成交量": "成交量", "成交额": "成交额",
        "换手率": "换手率", "流通市值": "流通市值",
        "最高": "最高", "最低": "最低",
        "今开": "开盘", "开盘": "开盘",
        "最高价": "最高", "最低价": "最低",
        "量比": "量比",
    }
    rename_dict = {k: v for k, v in column_map.items() if k in df.columns}
    df = df.rename(columns=rename_dict)

    required = ["代码", "名称", "最新价", "涨跌幅"]
    for col in required:
        if col not in df.columns:
            raise KeyError(f"实时行情缺少必要列: {col}，可用列: {list(df.columns)}")

    for col in ["最新价", "涨跌幅", "换手率", "量比", "流通市值", "最高", "最低", "开盘"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 过滤 ST、退市股
    df = df[~df["名称"].str.contains("ST|退|N", na=False)]

    logger.info("获取到 %d 支股票实时数据", len(df))
    return df


@retry(max_times=MAX_RETRY_TIMES, delay=2.0)
def get_daily_data(stock_code: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    获取个股日线历史数据（前复权）。

    Args:
        stock_code: 股票代码
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"
        adjust: qfq=前复权, hfq=后复权

    Returns:
        DataFrame：日期、开盘、收盘、最高、最低、成交量、成交额、换手率等
    """
    import akshare as ak

    logger.debug("获取 %s 日线数据: %s ~ %s", stock_code, start_date, end_date)
    df = ak.stock_zh_a_hist(
        symbol=stock_code, period="daily",
        start_date=start_date, end_date=end_date, adjust=adjust,
    )
    if df.empty:
        logger.warning("%s 在 %s ~ %s 无数据", stock_code, start_date, end_date)
        return df

    col_map = {
        "日期": "日期", "开盘": "开盘", "收盘": "收盘",
        "最高": "最高", "最低": "最低", "成交量": "成交量",
        "成交额": "成交额", "振幅": "振幅",
        "涨跌幅": "涨跌幅", "涨跌额": "涨跌额", "换手率": "换手率",
    }
    rename_dict = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=rename_dict)
    if "日期" in df.columns:
        df["日期"] = pd.to_datetime(df["日期"])
    return df


@retry(max_times=MAX_RETRY_TIMES, delay=3.0)
def get_all_history_data(stock_codes: list, start_date: str, end_date: str, max_workers: int = 10) -> dict:
    """
    批量获取多支股票的历史日线数据。

    Returns:
        dict: {stock_code: DataFrame}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info("开始批量下载 %d 支股票的历史数据...", len(stock_codes))
    results = {}
    failed = []

    def fetch_one(code: str) -> tuple:
        try:
            df = get_daily_data(code, start_date, end_date)
            return code, df
        except Exception as e:
            logger.error("下载 %s 失败: %s", code, e)
            return code, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, code): code for code in stock_codes}
        for future in as_completed(futures):
            code, df = future.result()
            if df is not None and not df.empty:
                results[code] = df
            else:
                failed.append(code)

    if failed:
        logger.warning("以下股票下载失败或无数据: %s", ", ".join(failed[:20]))
    logger.info("成功获取 %d / %d 支股票历史数据", len(results), len(stock_codes))
    return results


def get_market_status() -> dict:
    """获取当前市场状态（大盘指数实时行情）。"""
    try:
        df = get_realtime_quotes()
        market_info = {}
        for name, code in INDEX_CODES.items():
            row = df[df["代码"] == code]
            if not row.empty:
                market_info[name] = {"最新价": row.iloc[0]["最新价"], "涨跌幅": row.iloc[0]["涨跌幅"]}
        return market_info
    except Exception as e:
        logger.warning("获取市场状态失败: %s", e)
        return {}


def is_tail_time() -> bool:
    """判断当前时间是否在尾盘附近（14:30 ~ 15:00）。"""
    now = time.localtime()
    hour, minute = now.tm_hour, now.tm_min
    return (hour == 14 and minute >= 30) or (hour == 15 and minute == 0)
