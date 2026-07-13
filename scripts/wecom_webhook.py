import warnings
warnings.warn(
    "scripts/wecom_webhook.py is DEPRECATED. Use notifier/wecom_notifier.py instead."
    " See legacy/README.md for migration. This file will be removed after QL-014 stabilizes."
    , DeprecationWarning, stacklevel=2
)

#!/usr/bin/env python
"""
scripts/wecom_webhook.py — 企微 Webhook 推送公共模块

统一的企微群机器人 Webhook 封装，供所有 notify_*.py 脚本使用。

Webhook URL 读取优先级：
  1. 环境变量 WECOM_WEBHOOK_URL
  2. config.local.yaml → notifier.wecom_webhook
  3. config.yaml → notifier.wecom_webhook

用法：
  from wecom_webhook import push_markdown, push_text, get_webhook_url

  push_markdown("# 标题\\n**加粗**")
  push_text("纯文本消息")
"""
import os
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def get_webhook_url() -> str:
    """获取企微 Webhook URL，按优先级读取"""
    # 1. 环境变量
    env_url = os.environ.get("WECOM_WEBHOOK_URL", "").strip()
    if env_url:
        return env_url

    # 2. config.local.yaml
    try:
        import yaml
        local_cfg = ROOT / "config.local.yaml"
        if local_cfg.exists():
            data = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
            # 尝试多个可能的 key
            for key in ["notifier", "notify"]:
                section = data.get(key) or {}
                url = section.get("wecom_webhook", "").strip()
                if url:
                    return url
    except Exception:
        pass

    # 3. config.yaml
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        section = cfg.get("notifier") or {}
        url = section.get("wecom_webhook", "").strip()
        if url:
            return url
    except Exception:
        pass

    return ""


def push_markdown(content: str, webhook_url: str = None) -> bool:
    """推送企微 Markdown 消息

    Args:
        content: Markdown 格式消息正文
        webhook_url: 可选，不传则自动读取

    Returns:
        bool: 是否推送成功
    """
    url = webhook_url or get_webhook_url()
    if not url:
        logger.warning("⚠️ 未配置企微 Webhook URL，消息将打印到 stdout")
        print(content)
        return False

    body = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content}
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = resp.read().decode("utf-8")
        ok = '"errcode":0' in result
        if ok:
            logger.info("✅ 企微 Markdown 推送成功")
        else:
            logger.warning(f"⚠️ 企微返回异常: {result}")
        return ok
    except urllib.error.HTTPError as e:
        logger.error(f"❌ 企微推送 HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
        return False
    except Exception as e:
        logger.error(f"❌ 企微推送失败: {e}")
        return False


def push_text(content: str, webhook_url: str = None) -> bool:
    """推送企微纯文本消息

    Args:
        content: 纯文本消息正文
        webhook_url: 可选，不传则自动读取

    Returns:
        bool: 是否推送成功
    """
    url = webhook_url or get_webhook_url()
    if not url:
        logger.warning("⚠️ 未配置企微 Webhook URL，消息将打印到 stdout")
        print(content)
        return False

    body = json.dumps({
        "msgtype": "text",
        "text": {"content": content}
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = resp.read().decode("utf-8")
        ok = '"errcode":0' in result
        if ok:
            logger.info("✅ 企微 Text 推送成功")
        else:
            logger.warning(f"⚠️ 企微返回异常: {result}")
        return ok
    except urllib.error.HTTPError as e:
        logger.error(f"❌ 企微推送 HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
        return False
    except Exception as e:
        logger.error(f"❌ 企微推送失败: {e}")
        return False


def push_markdown_safe(content: str) -> bool:
    """安全推送 Markdown（不抛异常，失败只记日志）"""
    try:
        return push_markdown(content)
    except Exception as e:
        logger.error(f"push_markdown_safe 异常: {e}")
        return False


if __name__ == "__main__":
    # 自测
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    url = get_webhook_url()
    if url:
        print(f"✅ Webhook URL 已配置: {url[:50]}...")
        ok = push_markdown("# 🧪 测试消息\n\n这是来自 **wecom_webhook.py** 的自测消息。\n\n> 如果看到这条消息，说明 Webhook 配置正确。")
        print(f"推送结果: {'✅ 成功' if ok else '❌ 失败'}")
    else:
        print("⚠️ 未配置 Webhook URL，消息将打印到 stdout")
        push_markdown("# 测试\n\n这是 stdout 回退消息")
