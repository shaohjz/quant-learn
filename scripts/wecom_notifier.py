#!/usr/bin/env python3
"""
企微群机器人 Webhook 通知脚本 — 纯代码，无大模型依赖

使用方式：
  python scripts/wecom_notifier.py --type markdown --content "内容"
  python scripts/wecom_notifier.py --type text --content "内容" --mention "@all"
  python scripts/wecom_notifier.py --type image --path "图片路径"

配置：
  1. 在企微群里添加自定义机器人，获取 Webhook URL
  2. 将 URL 写入 config.yaml 的 notifier.wecom_webhook 字段
  3. 或设置环境变量 WECOM_WEBHOOK
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests

# 尝试导入 sim.config，失败则用环境变量
try:
    from sim.config import get as cfg_get
except ImportError:
    cfg_get = None

_WEBHOOK_TIMEOUT = 6  # 秒


def _get_webhook_url() -> Optional[str]:
    """获取企微 Webhook URL"""
    # 优先级：环境变量 > config
    url = os.environ.get("WECOM_WEBHOOK")
    
    if not url and cfg_get:
        url = cfg_get("notifier.wecom_webhook")
    
    if not url:
        # 尝试直接从 config.yaml 读取
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            try:
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    url = config.get("notifier", {}).get("wecom_webhook")
            except ImportError:
                # 没有 yaml 模块，尝试简单解析
                pass
    
    return url


def send_text(content: str, mentions: list = None) -> bool:
    """发送文本消息"""
    url = _get_webhook_url()
    if not url:
        print("❌ 未配置企微 Webhook URL")
        print("请在 config.yaml 中配置 notifier.wecom_webhook")
        return False
    
    payload = {
        "msgtype": "text",
        "text": {"content": content}
    }
    
    if mentions:
        payload["text"]["mentioned_list"] = mentions
    
    try:
        r = requests.post(url, json=payload, timeout=_WEBHOOK_TIMEOUT)
        result = r.json()
        if r.ok and result.get("errcode") == 0:
            print(f"✅ 文本消息发送成功")
            return True
        else:
            print(f"❌ 文本消息发送失败：{result}")
            return False
    except Exception as e:
        print(f"❌ 发送异常：{e}")
        return False


def send_markdown(content: str) -> bool:
    """发送 Markdown 消息"""
    url = _get_webhook_url()
    if not url:
        print("❌ 未配置企微 Webhook URL")
        return False
    
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content}
    }
    
    try:
        r = requests.post(url, json=payload, timeout=_WEBHOOK_TIMEOUT)
        result = r.json()
        if r.ok and result.get("errcode") == 0:
            print(f"✅ Markdown 消息发送成功")
            return True
        else:
            print(f"❌ Markdown 消息发送失败：{result}")
            return False
    except Exception as e:
        print(f"❌ 发送异常：{e}")
        return False


def send_image(image_path: str) -> bool:
    """发送图片（base64）"""
    url = _get_webhook_url()
    if not url:
        print("❌ 未配置企微 Webhook URL")
        return False
    
    p = Path(image_path)
    if not p.exists():
        print(f"❌ 图片不存在：{image_path}")
        return False
    
    try:
        # 读取图片并 base64 编码
        data = p.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        b64 = base64.b64encode(data).decode()
        
        payload = {
            "msgtype": "image",
            "image": {
                "base64": b64,
                "md5": md5
            }
        }
        
        r = requests.post(url, json=payload, timeout=_WEBHOOK_TIMEOUT * 2)
        result = r.json()
        if r.ok and result.get("errcode") == 0:
            print(f"✅ 图片发送成功")
            return True
        else:
            print(f"❌ 图片发送失败：{result}")
            return False
    except Exception as e:
        print(f"❌ 发送异常：{e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="企微群机器人 Webhook 通知脚本")
    parser.add_argument("--type", choices=["text", "markdown", "image"], 
                       default="text", help="消息类型")
    parser.add_argument("--content", type=str, help="消息内容（text/markdown）")
    parser.add_argument("--path", type=str, help="图片路径（image）")
    parser.add_argument("--mention", type=str, nargs="*", help="@成员列表")
    
    args = parser.parse_args()
    
    if args.type == "text":
        if not args.content:
            print("❌ text 类型需要 --content 参数")
            sys.exit(1)
        success = send_text(args.content, args.mention)
    elif args.type == "markdown":
        if not args.content:
            print("❌ markdown 类型需要 --content 参数")
            sys.exit(1)
        success = send_markdown(args.content)
    elif args.type == "image":
        if not args.path:
            print("❌ image 类型需要 --path 参数")
            sys.exit(1)
        success = send_image(args.path)
    else:
        print(f"❌ 不支持的消息类型：{args.type}")
        sys.exit(1)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
