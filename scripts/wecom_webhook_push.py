#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wecom_webhook_push.py — 企微自定义机器人 Webhook 推送（纯代码，无大模型依赖）

设计要点：
  1. 零大模型依赖：纯 Python 脚本，直接 POST 到企微 Webhook URL
  2. 配置来源：环境变量 WECOM_WEBHOOK > config.yaml notify.wecom_webhook > config.local.yaml notifier.wecom_webhook
  3. 支持 msgtype: text / markdown
  4. 失败不抛异常，仅打印错误到 stderr

用法：
  from wecom_webhook_push import push_markdown, push_text

  push_markdown("## 标题\\n**加粗**")
  push_text("纯文本消息", mentions=["@all"])
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("[wecom_webhook_push] ⚠️ 需要 requests 库: pip install requests", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]


def _load_webhook_url() -> Optional[str]:
    """从配置中读取企微 Webhook URL。

    优先级：
      1. config.local.yaml: notify.wecom_webhook（本地覆盖，不进 git）
      2. config.yaml: notify.wecom_webhook
      3. config.local.yaml: notifier.wecom_webhook（旧路径兼容）
      4. 环境变量 WECOM_WEBHOOK
    """
    def _is_valid(url):
        return url and url.strip() and 'YOUR_KEY' not in url

    # 1. config.local.yaml: notify.wecom_webhook
    try:
        import yaml
        local_cfg = ROOT / "config.local.yaml"
        if local_cfg.exists():
            cfg = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
            url = (cfg.get("notify") or {}).get("wecom_webhook", "")
            if _is_valid(url):
                return url.strip()
    except Exception:
        pass

    # 2. config.yaml: notify.wecom_webhook
    try:
        import yaml
        cfg_path = ROOT / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            url = (cfg.get("notify") or {}).get("wecom_webhook", "")
            if _is_valid(url):
                return url.strip()
    except Exception:
        pass

    # 3. config.local.yaml: notifier.wecom_webhook（旧路径）
    try:
        import yaml
        local_cfg = ROOT / "config.local.yaml"
        if local_cfg.exists():
            cfg = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
            url = (cfg.get("notifier") or {}).get("wecom_webhook", "")
            if _is_valid(url):
                return url.strip()
    except Exception:
        pass

    # 4. 环境变量
    env_url = os.environ.get("WECOM_WEBHOOK")
    if _is_valid(env_url):
        return env_url.strip()

    return None


def _post(payload: dict, timeout: int = 10) -> bool:
    """POST 到企微 Webhook，返回是否成功。"""
    url = _load_webhook_url()
    if not url:
        print("[wecom_webhook_push] ⚠️ Webhook URL 未配置，跳过推送", file=sys.stderr)
        print(f"[wecom_webhook_push] payload={json.dumps(payload, ensure_ascii=False)[:200]}", file=sys.stderr)
        return False

    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        result = r.json()
        if result.get("errcode", 0) == 0:
            return True
        else:
            print(f"[wecom_webhook_push] ⚠️ 企微返回错误: {result}", file=sys.stderr)
            return False
    except requests.exceptions.Timeout:
        print(f"[wecom_webhook_push] ⚠️ POST 超时 ({timeout}s)", file=sys.stderr)
        return False
    except requests.exceptions.RequestException as e:
        print(f"[wecom_webhook_push] ⚠️ POST 失败: {e}", file=sys.stderr)
        return False


def push_text(content: str, mentioned_list: Optional[list] = None) -> bool:
    """发送纯文本消息。

    Args:
        content: 文本内容
        mentioned_list: @ 的用户列表，如 ["@all"] 或 ["userid1", "userid2"]

    Returns:
        bool: 是否发送成功
    """
    payload = {
        "msgtype": "text",
        "text": {
            "content": content,
            "mentioned_list": mentioned_list or [],
        },
    }
    return _post(payload)


def push_markdown(content: str) -> bool:
    """发送 Markdown 消息（企微有限 Markdown 子集）。

    支持格式：
      - 标题: # ## ###
      - 加粗: **text**
      - 链接: [text](url)
      - 引用: > text
      - 代码块: ```code```
      - 列表: - item

    Args:
        content: Markdown 内容

    Returns:
        bool: 是否发送成功
    """
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": content,
        },
    }
    return _post(payload)


def push_card(title: str, description: str = "", url: str = "", picurl: str = "") -> bool:
    """发送卡片消息（企微 news 类型）。

    Args:
        title: 卡片标题
        description: 卡片描述
        url: 点击跳转链接
        picurl: 图片 URL

    Returns:
        bool: 是否发送成功
    """
    payload = {
        "msgtype": "news",
        "news": {
            "articles": [
                {
                    "title": title,
                    "description": description,
                    "url": url,
                    "picurl": picurl,
                }
            ]
        },
    }
    return _post(payload)


# ── CLI 入口 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="企微机器人 Webhook 推送（纯代码版）")
    sub = parser.add_subparsers(dest="command")

    # text
    p_text = sub.add_parser("text", help="发送纯文本")
    p_text.add_argument("--content", default="", help="消息内容")
    p_text.add_argument("--mentioned", default="", help="@ 的用户，逗号分隔")
    p_text.add_argument("--stdin", action="store_true", help="从 stdin 读内容")

    # markdown
    p_mark = sub.add_parser("markdown", help="发送 Markdown")
    p_mark.add_argument("--content", default="", help="Markdown 内容")
    p_mark.add_argument("--stdin", action="store_true", help="从 stdin 读内容")

    # card
    p_card = sub.add_parser("card", help="发送卡片")
    p_card.add_argument("--title", required=True, help="卡片标题")
    p_card.add_argument("--content", default="", help="卡片描述")
    p_card.add_argument("--url", default="", help="点击跳转链接")
    p_card.add_argument("--picurl", default="", help="图片 URL")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command in ("text", "markdown"):
        if args.stdin:
            content = sys.stdin.read().strip()
        else:
            content = args.content
        if not content:
            print("[wecom_webhook_push] ⚠️ 内容为空", file=sys.stderr)
            sys.exit(1)

        if args.command == "text":
            mentioned = args.mentioned.split(",") if args.mentioned else []
            ok = push_text(content, mentioned_list=mentioned)
        else:
            ok = push_markdown(content)
    elif args.command == "card":
        ok = push_card(args.title, description=args.content, url=args.url, picurl=args.picurl)
    else:
        ok = False

    sys.exit(0 if ok else 1)
