# A股尾盘买入量化策略系统

> 基于因子筛选和凯利公式的 A 股尾盘量化选股策略，支持回测、参数优化和自动化运行。

---

## 策略逻辑

### 核心思路

1. **尾盘买入**：每日 14:35 获取 A 股实时行情，收盘前约 25 分钟筛选股票。
2. **因子筛选**：
   - `ret_1450`：尾盘相对开盘涨幅
   - `volume_ratio`：量比
   - `close_position`：收盘位置 (现价-最低)/(最高-最低)
   - `turnover_rate`：换手率
   - `market_cap`：流通市值
3. **凯利公式仓位**：根据回测胜率和盈亏比，计算最优买入金额（半凯利/1/4凯利）。
4. **T+1 卖出**：次日止盈(+3%)/止损(-3%)/收盘卖出。

### 收益来源

尾盘动量延续——筛选当日尾盘走强、有资金推动、次日有望延续上涨的股票。

---

## 项目结构

```
tail_strategy/
├── data/                          # 历史数据（运行时自动下载）
├── logs/                          # 日志输出
├── src/
│   ├── __init__.py
│   ├── data_fetcher.py            # 获取实时行情（akshare）及历史数据
│   ├── feature_engine.py          # 尾盘特征计算
│   ├── backtest_engine.py         # 回测核心逻辑
│   ├── factor_optimizer.py        # 网格搜索最优因子阈值
│   ├── daily_picker.py            # 每日选股主程序（含凯利公式）
│   ├── email_sender.py            # 发送 HTML 邮件
│   └── utils.py                   # 辅助函数（日志、重试等）
├── config/
│   └── settings.py                # 全局配置
├── .github/workflows/
│   └── daily_tail.yml             # GitHub Actions 定时任务
├── run_backtest.py                # 回测入口
├── run_optimization.py            # 因子优化入口
├── run_daily_pick.py              # 每日选股入口
├── requirements.txt               # Python 依赖
├── .env.example                   # 环境变量模板
└── README.md                      # 本文件
```

---

## 安装指南

### 前置条件

- Python 3.8+
- pip

### 安装步骤

```bash
# 1. 进入项目目录
cd tail_strategy

# 2. 创建虚拟环境（推荐）
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置邮箱
cp .env.example .env
# 编辑 .env 文件填入邮箱信息
```

---

## 配置邮箱

### QQ 邮箱获取授权码

1. 登录 [QQ 邮箱](https://mail.qq.com)
2. 设置 → 账户 → POP3/IMAP/SMTP服务
3. 开启服务并生成授权码（16位）
4. 填入 `.env` 文件：

```ini
EMAIL_USER=123456789@qq.com
EMAIL_PASSWORD=你的16位授权码
```

---

## 使用流程

### 第一步：因子优化（建议先做）

```bash
python run_optimization.py --sample 100
```

遍历因子参数组合，按「胜率 × 盈亏比」评分，自动更新 settings.py。

### 第二步：回测验证

```bash
python run_backtest.py
```

使用最优参数跑回测，查看胜率、盈亏比等指标。

### 第三步：每日选股

```bash
# 试运行（不发送邮件）
python run_daily_pick.py --dry-run

# 正式运行
python run_daily_pick.py
```

---

## 📱 手机上看选股结果（推荐）

不用开电脑，手机上打开一个网址就能看到当天推荐买入的股票和仓位。

### 设置步骤（只需一次）

```bash
# 1. 在 GitHub 上创建仓库，把代码推上去
git init
git add .
git commit -m "初始提交"
git remote add origin https://github.com/你的用户名/tail_strategy.git
git push -u origin main

# 2. 在 GitHub 仓库页面启用 GitHub Pages：
#    Settings → Pages → Source 选 "GitHub Actions"
#    （工作流已写好，无需额外配置）

# 3. 添加 Secrets：
#    仓库 → Settings → Secrets and variables → Actions → New repository secret
```

| Secret | 说明 |
|---|---|
| `EMAIL_USER` | QQ邮箱地址 |
| `EMAIL_PASSWORD` | SMTP授权码 |
| `EMAIL_TO` | 收件人（可选，默认发给自己） |

### 完成后每天的操作

```
14:35  GitHub Actions 自动运行策略
   ↓
14:36  收到邮件（手机上打开）
   ↓
       或打开 GitHub Pages 网址：
       https://你的用户名.github.io/tail_strategy/
       ↓
       看到今天推荐的股票 + 建议买入金额
       ↓
       直接在券商 APP 下单
```

> 💡 **手机浏览器打开网址后，可以添加到桌面**（iOS Safari: 分享 → 添加到主屏幕；Android Chrome: 菜单 → 添加到主屏幕），之后就像打开一个原生 APP 一样方便。

### 效果示例

打开网页后你会看到这样的界面（已针对手机屏幕优化）：

```
┌─────────────────────┐
│  A股尾盘买入策略    │
│  2026年6月2日 周四  │
│          交易中 ●   │
├──────────┬──────────┤
│ 策略参数 │ 回测表现 │
│ 涨幅2~3% │ 胜率62.9%│
│ 位置≥0.8 │ 盈亏比1.4│
│ ...      │ ...      │
├──────────┴──────────┤
│ 今日选股结果  3支  │
│                    │
│ 深天马A  +2.34%   │
│ 建议买入 15.0万   │
│                    │
│ 华润双鹤 +2.61%   │
│ 建议买入 15.0万   │
│                    │
│ 总仓位: 40%        │
│ 剩余现金: 60万     │
├─────────────────────┤
│ 下单指引            │
│ 14:35~14:50 买入   │
│ 次日 +3%/-3% 卖出  │
└─────────────────────┘
```

---

## GitHub Actions 自动运行

### 设置 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret

| Secret Name | 说明 |
|---|---|
| `EMAIL_USER` | 邮箱地址 |
| `EMAIL_PASSWORD` | SMTP 授权码 |
| `EMAIL_TO` | 收件人（可选） |

### 触发

- **自动**：工作日 14:35 CST
- **手动**：Actions → 每日选股 + 部署 → Run workflow

### 工作流说明

更新后的工作流会：
1. 运行 `run_daily_pick.py` → **发送邮件到手机**
2. 运行 `update_dashboard.py` → 导出数据
3. 部署到 **GitHub Pages** → 手机打开网页也能看

---

## 常见问题

### Q: akshare 连接失败？
A: 网络问题，可尝试代理或更换数据源。GitHub Actions 在国外服务器，akshare 可能不稳定。

### Q: 邮件发送失败？
A: 检查授权码是否正确、SMTP 服务是否开启、端口是否被屏蔽。

### Q: 回测结果不理想？
A: 调整 PARAM_GRID 搜索范围、修改止盈止损参数、更换回测时间段或增加新因子。

### Q: 优化太慢？
A: 减少股票样本数：`python run_optimization.py --sample 50`

---

## 风险提示

**股市有风险，投资需谨慎。** 本系统仅供参考，不构成投资建议。历史回测不代表未来收益。
