"""
辅助工具模块
============
统一日志配置、日期处理、重试装饰器等工具函数。
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable, Any


def setup_logger(name: str = "tail_strategy") -> logging.Logger:
    """
    配置并返回日志记录器。
    日志同时输出到控制台和 logs/ 目录下的按日滚动的文件。

    Args:
        name: 日志记录器名称

    Returns:
        配置好的 Logger 实例
    """
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    console_handler.setFormatter(console_fmt)

    today_str = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f"strategy_{today_str}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s")
    file_handler.setFormatter(file_fmt)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


logger = setup_logger()


def retry(max_times: int = 3, delay: float = 2.0, exceptions: tuple = (Exception,)):
    """
    重试装饰器：在指定异常发生时自动重试。
    """
    import time

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exc = None
            for attempt in range(1, max_times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    logger.warning("%s 第 %d/%d 次失败: %s", func.__name__, attempt, max_times, e)
                    if attempt < max_times:
                        time.sleep(delay * attempt)
            logger.error("%s 重试 %d 次后仍然失败", func.__name__, max_times)
            raise last_exc
        return wrapper
    return decorator


def get_trade_dates(start_date: str, end_date: str) -> list:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def is_trade_day(dt: datetime = None) -> bool:
    if dt is None:
        dt = datetime.now()
    return dt.weekday() < 5


def format_cny(value: float) -> str:
    if abs(value) >= 10000:
        return f"{value / 10000:,.2f} 万元"
    return f"{value:,.2f} 元"
