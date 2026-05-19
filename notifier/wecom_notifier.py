"""notifier/wecom_notifier.py — 企微群机器人推送封装

设计要点：
1. 默认从 config.local.yaml 的 notifier.wecom_webhook 读 URL（与老 portfolio_alert 行为一致）。
2. dry_run=True 时仅打印 + 写日志，不真发；用于 vnpy 迁移期回归测试。
3. 失败不抛异常，避免拖死策略主循环。

用法：
    from notifier import push_text, get_default_notifier
    push_text("🚨 触发止损：600330 跌破 27.00")
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def _load_webhook_from_local_cfg() -> Optional[str]:
    """从 config.local.yaml 读 webhook，没有就返回 None"""
    try:
        import yaml  # type: ignore
        local_cfg = ROOT / "config.local.yaml"
        if local_cfg.exists():
            data = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
            return (data.get("notifier") or {}).get("wecom_webhook") or None
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 config.local.yaml 失败: %s", e)
    return None


class WecomNotifier:
    """企微群机器人推送器（线程安全弱要求，调用频率低无需加锁）"""

    def __init__(self, webhook_url: Optional[str] = None, dry_run: bool = False):
        # 优先级：显式传参 > 环境变量 > config.local.yaml
        self.webhook_url = (
            webhook_url
            or os.environ.get("WECOM_WEBHOOK")
            or _load_webhook_from_local_cfg()
        )
        # 环境变量 NOTIFIER_DRY_RUN=1 可全局强制 dry-run（迁移期默认开启）
        self.dry_run = bool(dry_run) or os.environ.get("NOTIFIER_DRY_RUN", "1") == "1"

    def push_text(self, content: str, mentioned_list: Optional[list] = None) -> bool:
        """推送一条文本，dry_run 模式下仅打印。返回是否发送成功。"""
        if self.dry_run or not self.webhook_url:
            logger.info("[dry-run/notifier] %s", content.replace("\n", " | "))
            print(f"[dry-run wecom] {content}")
            return True

        body = {"msgtype": "text", "text": {"content": content}}
        if mentioned_list:
            body["text"]["mentioned_list"] = mentioned_list
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
            ok = '"errcode":0' in resp
            if ok:
                logger.info("webhook 推送成功: %s", content[:40])
            else:
                logger.warning("webhook 异常返回: %s", resp)
            return ok
        except Exception as e:  # noqa: BLE001
            logger.error("webhook 推送失败: %s", e)
            return False


_default: Optional[WecomNotifier] = None


def get_default_notifier(dry_run: Optional[bool] = None) -> WecomNotifier:
    """获取全局单例"""
    global _default
    if _default is None:
        _default = WecomNotifier(dry_run=dry_run if dry_run is not None else False)
    return _default


def push_text(content: str) -> bool:
    return get_default_notifier().push_text(content)
