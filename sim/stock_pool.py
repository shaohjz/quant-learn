"""
sim/stock_pool.py
股票池管理（从 config.yaml 读取）
"""

from sim.config import stock_pool_enabled


class StockPool:
    """股票池管理器"""

    def __init__(self):
        # 从配置文件加载启用的股票池
        self._pool = stock_pool_enabled() or {}

    def get_all(self) -> dict:
        return dict(self._pool)

    def get_codes(self) -> list:
        return list(self._pool.keys())

    def add(self, code: str, name: str = ""):
        self._pool[code] = name

    def remove(self, code: str):
        self._pool.pop(code, None)

    def __contains__(self, code):
        return code in self._pool

    def __len__(self):
        return len(self._pool)

    def __repr__(self):
        return f"StockPool({self._pool})"
