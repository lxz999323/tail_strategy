"""
邮件发送模块
============
通过 SMTP 发送 HTML 格式选股报告邮件。
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime
import pandas as pd
from src.utils import logger
from config.settings import EMAIL_USER, EMAIL_PASSWORD, EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_USE_SSL, EMAIL_TO, TOTAL_CAPITAL


def _build_html_table(df: pd.DataFrame) -> str:
    """将 DataFrame 转为 HTML 表格。"""
    if df.empty:
        return ""

    display_cols = {
        "代码": "股票代码", "名称": "股票名称", "ret_1450": "尾盘涨幅(%)",
        "volume_ratio": "量比", "turnover_rate": "换手率(%)",
        "market_cap": "流通市值(亿)", "close_position": "收盘位置",
        "capped_amount": "建议买入(元)", "half_kelly_amount": "半凯利(元)",
        "quarter_kelly_amount": "1/4凯利(元)",
    }
    cols = [k for k in display_cols if k in df.columns]

    rows = ""
    for _, row in df.iterrows():
        rows += "<tr>"
        for col in cols:
            val = row.get(col, "")
            if isinstance(val, float):
                if col in ("ret_1450", "turnover_rate"):
                    formatted = f"{val:.2f}"
                elif col == "close_position":
                    formatted = f"{val:.2f}"
                else:
                    formatted = f"{val:,.2f}"
            else:
                formatted = str(val)
            rows += f"<td>{formatted}</td>"
        rows += "</tr>"

    headers = "".join(f"<th>{display_cols[c]}</th>" for c in cols)
    return f"""
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:14px;font-family:Arial,sans-serif;width:100%;">
        <thead style="background-color:#2c3e50;color:white;"><tr>{headers}</tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def send_html_report(df_stocks: pd.DataFrame, total_capital: float = TOTAL_CAPITAL,
                     to_emails: list = None, email_user: str = None, email_password: str = None,
                     smtp_host: str = None, smtp_port: int = None, use_ssl: bool = None) -> bool:
    """
    发送 HTML 格式选股报告邮件。

    Args:
        df_stocks: 选股结果（空 DataFrame 表示无信号）
        total_capital: 总资金
        to_emails: 收件人列表

    Returns:
        bool: 是否发送成功
    """
    if to_emails is None: to_emails = EMAIL_TO
    if email_user is None: email_user = EMAIL_USER
    if email_password is None: email_password = EMAIL_PASSWORD
    if smtp_host is None: smtp_host = EMAIL_SMTP_HOST
    if smtp_port is None: smtp_port = EMAIL_SMTP_PORT
    if use_ssl is None: use_ssl = EMAIL_USE_SSL

    if not email_user or not email_password:
        logger.error("邮箱配置不完整，请设置 EMAIL_USER 和 EMAIL_PASSWORD")
        return False

    if not to_emails or to_emails == [""]:
        to_emails = [email_user]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if df_stocks.empty:
        # 无信号 - 纯文本
        body = f"""A股尾盘买入策略 - 选股报告

时间：{now}

今日无尾盘买入信号，建议空仓。

此邮件由量化策略系统自动发送，仅供参考，不构成投资建议。
"""
        msg = MIMEText(body, "plain", "utf-8")
        subject = f"[尾盘策略] 今日无信号 - {datetime.now().strftime('%m/%d')}"
        logger.info("无信号，发送空仓提示")
    else:
        # 有信号 - HTML
        html_table = _build_html_table(df_stocks)
        total_suggested = df_stocks["capped_amount"].sum() if "capped_amount" in df_stocks.columns else 0
        pct = total_suggested / total_capital * 100 if total_capital > 0 else 0

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>尾盘策略选股报告</title></head>
<body style="font-family:Arial,sans-serif;background:#f5f7fa;padding:20px;">
<div style="max-width:800px;margin:0 auto;background:white;border-radius:10px;padding:30px;box-shadow:0 2px 10px rgba(0,0,0,0.1);">
<h1 style="color:#2c3e50;border-bottom:3px solid #3498db;padding-bottom:10px;">A股尾盘买入策略 · 选股报告</h1>
<p style="color:#7f8c8d;font-size:14px;">{now} | 总资金: {total_capital/10000:.0f}万 | 建议使用: {total_suggested/10000:.1f}万 ({pct:.1f}%)</p>
<h2 style="color:#2980b9;">今日入选股票</h2>
{html_table}
<div style="margin-top:20px;padding:15px;background:#fef9e7;border-left:4px solid #f39c12;border-radius:4px;">
<p style="margin:5px 0;color:#7f8c8d;font-size:12px;"><strong>免责声明:</strong> 本报告由系统自动生成，仅供参考，不构成投资建议。股市有风险，投资需谨慎。</p>
</div>
<p style="color:#bdc3c7;font-size:12px;margin-top:20px;text-align:center;">由 A股尾盘买入量化策略系统 自动发送</p>
</div></body></html>"""

        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html, "html", "utf-8"))
        msg.attach(MIMEText(f"请使用支持 HTML 的邮件客户端查看本报告。\n\n共 {len(df_stocks)} 支股票入选。", "plain", "utf-8"))
        subject = f"[尾盘策略] {len(df_stocks)} 支入选 - {datetime.now().strftime('%m/%d')}"
        logger.info("发送选股报告，%d 支股票", len(df_stocks))

    msg["From"] = f"尾盘策略 <{email_user}>"
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = Header(subject, "utf-8")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as s:
                s.login(email_user, email_password)
                s.sendmail(email_user, to_emails, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
                s.starttls()
                s.login(email_user, email_password)
                s.sendmail(email_user, to_emails, msg.as_string())
        logger.info("邮件发送成功 -> %s", to_emails)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP 认证失败，请检查邮箱地址和授权码")
        return False
    except smtplib.SMTPException as e:
        logger.error("SMTP 发送失败: %s", e)
        return False
    except Exception as e:
        logger.error("邮件发送异常: %s", e)
        return False
