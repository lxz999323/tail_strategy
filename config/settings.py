"""
A股尾盘买入量化策略系统 - 全局配置
===============================
所有敏感信息通过环境变量读取，不要在代码中硬编码。
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件（若存在）
load_dotenv()

# ============================================================
# 资金管理
# ============================================================
TOTAL_CAPITAL = 1_000_000  # 初始总资金（元）
MAX_POSITIONS = 5          # 最大同时持仓数
OVERHEAT_LIMIT = 15        # 候选股票超过此数视为市场过热，放弃交易

# ============================================================
# 止盈止损
# ============================================================
STOP_GAIN = 0.03           # 止盈线 +3%
STOP_LOSS = -0.03          # 止损线 -3%

# ============================================================
# 回测参数
# ============================================================
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2023-12-31"
BACKTEST_WIN_RATE = 0.55       # 回测胜率（示例值，优化后覆盖）
BACKTEST_PROFIT_FACTOR = 1.5   # 回测盈亏比（示例值，优化后覆盖）

# ============================================================
# 最优因子阈值（从 factor_optimizer.py 网格搜索得到）
# 初次使用时运行 python run_optimization.py 自动填充
# ============================================================
BEST_THRESHOLDS = {
    "ret_min": 1.5,
    "ret_max": 5.0,
    "volume_ratio_min": 1.2,
    "close_pos_min": 0.7,
    "turnover_min": 3.0,
    "turnover_max": 15.0,
    "market_cap_min": 30,
    "market_cap_max": 150,
}

# ============================================================
# 邮箱配置（通过环境变量读取）
# ============================================================
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.qq.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "true").lower() == "true"
EMAIL_TO = os.getenv("EMAIL_TO", "").split(",") if os.getenv("EMAIL_TO") else [EMAIL_USER]

# ============================================================
# 数据获取
# ============================================================
REALTIME_QUOTE_TIMEOUT = 30
HISTORY_DATA_TIMEOUT = 60
MAX_RETRY_TIMES = 3
TAIL_SNAPSHOT_TIME = "14:50"
