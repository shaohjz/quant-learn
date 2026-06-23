#!/usr/bin/env python
"""
wecom_webhook.py — 企业微信 Webhook 推送模块

功能：
  - 从 config.yaml 读取企业微信 Webhook URL
  - 提供 push_markdown 函数推送 Markdown 消息
  - 提供 get_webhook_url 函数获取配置的 Webhook URL

用法：
  from wecom_webhook import push_markdown, get_webhook_url
  
  url = get_webhook_url()
  if url:
      push_markdown(content)
"""

import json
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent


def _load_webhook_url():
    """从 config.yaml 读取企业微信 Webhook URL"""
    try:
        import yaml
        config_path = ROOT / "config.yaml"
        if not config_path.exists():
            logger.warning(f"config.yaml 不存在: {config_path}")
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        
        # 尝试多个可能的配置路径
        url = None
        
        # 1. notify.wecom_webhook
        if 'notify' in cfg:
            url = cfg['notify'].get('wecom_webhook', '')
        
        # 2. notifier.wecom_webhook (兼容旧配置)
        if not url and 'notifier' in cfg:
            url = cfg['notifier'].get('wecom_webhook', '')
        
        # 3. wecom_webhook (直接配置)
        if not url:
            url = cfg.get('wecom_webhook', '')
        
        if url:
            return url
        else:
            logger.warning("未找到企业微信 Webhook URL 配置")
            return None
            
    except Exception as e:
        logger.error(f"读取 Webhook URL 失败: {e}")
        return None


def get_webhook_url():
    """获取企业微信 Webhook URL"""
    return _load_webhook_url()


def push_markdown(content: str) -> bool:
    """推送 Markdown 消息到企业微信
    
    Args:
        content: Markdown 格式的消息内容
        
    Returns:
        bool: 推送是否成功
    """
    url = get_webhook_url()
    if not url:
        logger.warning("Webhook URL 未配置，无法推送")
        return False
    
    try:
        # 企业微信 Webhook API 格式
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('errcode') == 0:
                logger.info("✅ 企业微信推送成功")
                return True
            else:
                logger.error(f"❌ 企业微信推送失败: {result}")
                return False
                
    except Exception as e:
        logger.error(f"❌ 推送失败: {e}")
        return False


def push_text(content: str) -> bool:
    """推送纯文本消息到企业微信
    
    Args:
        content: 文本消息内容
        
    Returns:
        bool: 推送是否成功
    """
    url = get_webhook_url()
    if not url:
        logger.warning("Webhook URL 未配置，无法推送")
        return False
    
    try:
        payload = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('errcode') == 0:
                logger.info("✅ 企业微信推送成功")
                return True
            else:
                logger.error(f"❌ 企业微信推送失败: {result}")
                return False
                
    except Exception as e:
        logger.error(f"❌ 推送失败: {e}")
        return False


if __name__ == '__main__':
    # 测试推送功能
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    url = get_webhook_url()
    print(f"Webhook URL: {'已配置' if url else '未配置'}")
    
    if url:
        test_content = """# 测试消息
        
## 这是一条测试消息

- 测试项1
- 测试项2

> 如果有收到这条消息，说明 Webhook 配置正确
"""
        success = push_markdown(test_content)
        print(f"推送结果: {'成功' if success else '失败'}")
    else:
        print("请先在 config.yaml 中配置 notify.wecom_webhook")
