"""notifier 包：统一封装企微 webhook 推送。

旧代码（scripts/portfolio_alert.py 等）里有内联的 webhook 推送函数；
迁移到 vnpy 之后，所有策略 / runner 都通过本模块调用，方便统一加 dry_run / 重试 / 限流。
"""
from .wecom_notifier import WecomNotifier, get_default_notifier, push_text  # noqa: F401
