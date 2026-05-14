"""
sim/notifier.py
推送通知 — 支持企业微信群机器人和 OpenClaw 内部消息

【企微群机器人】最简单：建一个企微群 → 添加群机器人 → 拿到 webhook URL → 写到
config.local.yaml 的 notifier.wecom_webhook 里即可。文档：
  https://developer.work.weixin.qq.com/document/path/91770

【OpenClaw 直推】当 quant-learn 跑在 OpenClaw 同一台机器上时，
可以走 OpenClaw 的本地 message API（暂不实现，先用企微 webhook）。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from sim.config import get as cfg_get


_WEBHOOK_TIMEOUT = 6  # 秒


def _wecom_webhook_url() -> Optional[str]:
    return os.environ.get("WECOM_WEBHOOK") or cfg_get("notifier.wecom_webhook")


def _enabled() -> bool:
    flag = os.environ.get("NOTIFY_ENABLED")
    if flag is not None:
        return flag.lower() in ("1", "true", "yes", "on")
    return bool(cfg_get("notifier.enabled", True))


def send_text(text: str, mentions: list = None) -> bool:
    """发文本消息到企微群机器人；mentions=['@all'] 或具体 userid"""
    if not _enabled():
        return False
    url = _wecom_webhook_url()
    if not url:
        print("ℹ notifier 未配置 webhook，跳过推送")
        return False

    payload = {"msgtype": "text", "text": {"content": text}}
    if mentions:
        payload["text"]["mentioned_list"] = mentions

    try:
        r = requests.post(url, json=payload, timeout=_WEBHOOK_TIMEOUT)
        ok = r.ok and r.json().get("errcode") == 0
        if not ok:
            print(f"⚠ 推送失败：{r.status_code} {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"⚠ 推送异常：{e}")
        return False


def send_markdown(content: str) -> bool:
    """发 Markdown 消息（企微只支持有限子集）"""
    if not _enabled():
        return False
    url = _wecom_webhook_url()
    if not url:
        return False
    try:
        r = requests.post(url, json={
            "msgtype": "markdown",
            "markdown": {"content": content},
        }, timeout=_WEBHOOK_TIMEOUT)
        return r.ok and r.json().get("errcode") == 0
    except Exception as e:
        print(f"⚠ 推送异常：{e}")
        return False


def send_image(image_path: str) -> bool:
    """发本地图片（base64）"""
    if not _enabled():
        return False
    url = _wecom_webhook_url()
    if not url:
        return False
    p = Path(image_path)
    if not p.exists():
        print(f"⚠ 图片不存在：{image_path}")
        return False

    import base64, hashlib
    data = p.read_bytes()
    md5 = hashlib.md5(data).hexdigest()
    b64 = base64.b64encode(data).decode()
    try:
        r = requests.post(url, json={
            "msgtype": "image",
            "image": {"base64": b64, "md5": md5},
        }, timeout=_WEBHOOK_TIMEOUT * 2)
        return r.ok and r.json().get("errcode") == 0
    except Exception as e:
        print(f"⚠ 推送异常：{e}")
        return False


# ---------- 业务封装 ----------
def notify_signals(signals: list, trade_date=None):
    """推送盘前信号"""
    if not signals:
        return
    today = trade_date or datetime.now().date()
    lines = [f"🌅 **盘前信号** | {today}\n"]
    has_action = False
    for s in signals:
        emoji = "🟢" if s["signal"] == "BUY" else "🔴" if s["signal"] == "SELL" else "⚪"
        if s["signal"] != "HOLD":
            has_action = True
        lines.append(f"{emoji} **{s['name']}**({s['code']}) — {s['signal']} @¥{s['price']:.2f}")
        lines.append(f"  > {', '.join(s['reasons'])}")
    suffix = "" if has_action else "\n（今日无买卖动作）"
    send_markdown("\n".join(lines) + suffix)


def notify_trade(side: str, name: str, code: str, qty: int, price: float,
                 reason: str, success: bool):
    """推送成交"""
    emoji = "✅" if success else "❌"
    side_emoji = "🟢买入" if side == "BUY" else "🔴卖出"
    text = (
        f"{emoji} {side_emoji} {name}({code})\n"
        f"   {qty}股 @ ¥{price:.4f} = ¥{qty * price:,.2f}\n"
        f"   信号：{reason}"
    )
    send_text(text)


def notify_daily_report(report: str, chart_path: str = None):
    """推送日报（文本+图）"""
    send_markdown(report)
    if chart_path and os.path.exists(chart_path):
        send_image(chart_path)


if __name__ == "__main__":
    # 自检
    ok = send_text(f"📡 quant-learn 通知测试 - {datetime.now()}")
    print("test result:", ok)
