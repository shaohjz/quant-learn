"""
sim/stock_pool.py
股票池管理（从 config.yaml 读取）
"""

from sim.config import get


def _load_stock_pool():
    """从配置文件加载股票池
    
    优先使用 stock_pool 配置，如果为空则使用 watchlist.user_manual 中启用的股票
    """
    # 首先尝试从 stock_pool 配置加载
    pool = get("stock_pool", []) or []
    if pool:
        out = {}
        for item in pool:
            if item.get("enabled", True):
                out[item["code"]] = item.get("name", "")
        return out
    
    # 如果 stock_pool 为空，则从 watchlist.user_manual 加载启用的股票
    watchlist = get("watchlist.user_manual", {}) or {}
    out = {}
    for code, info in watchlist.items():
        if info.get("enabled", False):
            out[code] = info.get("name", "")
    return out


class StockPool:
    """股票池管理器"""

    def __init__(self):
        # 从配置文件加载启用的股票池
        self._pool = _load_stock_pool()

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
