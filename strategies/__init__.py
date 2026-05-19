# strategies package
"""老的自研框架策略（sma_cross / macd_strategy / composite_v2 / ...）继续保留，
新增的 vnpy 风格策略放在同目录，按需导入。"""

# vnpy 策略（如果 vnpy 没装好这里 import 会失败，所以 try）
try:
    from .threshold_alert_strategy import ThresholdAlertStrategy  # noqa: F401
    from .fusion_strategy import FusionStrategy  # noqa: F401
except Exception as _e:  # noqa: BLE001
    import logging
    logging.getLogger(__name__).debug("vnpy strategies 导入跳过: %s", _e)
