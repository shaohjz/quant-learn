"""
vqlearn/gateways/qmt_data.py — mini-QMT xtdata 行情接口封装

封装 xtquant.xtdata，提供：
- connect()              连接 mini-QMT（自动找端口）
- download_history()     下载历史 K 线
- get_kline()            拉取 K 线 DataFrame
- get_tick()             拉取盘口 tick
- subscribe_quote()      订阅实时行情（callback）

国金 mini-QMT 默认端口 58600（不是 58610 投研版）。
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT_CANDIDATES = [58600, 58610, 58611, 58612]


class QmtDataGateway:
    """xtdata 数据接口封装（行情 only，不含交易）"""

    def __init__(self, port: Optional[int] = None) -> None:
        self.port = port
        self.connected = False

    def connect(self) -> bool:
        """连接到本地 mini-QMT 行情服务"""
        from xtquant import xtdata

        ports = [self.port] if self.port else DEFAULT_PORT_CANDIDATES
        for p in ports:
            try:
                xtdata.reconnect("localhost", p)
                self.port = p
                self.connected = True
                logger.info(f"xtdata 已连接 localhost:{p}")
                return True
            except Exception as e:
                logger.debug(f"xtdata 连接 {p} 失败: {e}")
        raise RuntimeError(f"xtdata 无法连接，已尝试端口: {ports}")

    @staticmethod
    def normalize_code(code: str) -> str:
        """002256 → 002256.SZ；600330 → 600330.SH；603 / 605 / 688 / 11 / 12 → SH"""
        if "." in code:
            return code.upper()
        if code.startswith(("60", "68", "11", "12", "5")):
            return f"{code}.SH"
        if code.startswith(("00", "30", "15", "16")):
            return f"{code}.SZ"
        if code.startswith(("83", "87", "92", "43")):
            return f"{code}.BJ"
        return f"{code}.SH"  # 兜底

    def download_history(
        self,
        codes: Iterable[str],
        period: str = "1d",
        start_time: str = "20250101",
        end_time: str = "",
    ) -> Dict[str, bool]:
        """批量下载历史 K 线到本地缓存"""
        from xtquant import xtdata

        results = {}
        for raw in codes:
            code = self.normalize_code(raw)
            try:
                xtdata.download_history_data(code, period=period, start_time=start_time, end_time=end_time)
                results[code] = True
            except Exception as e:
                logger.warning(f"download {code} 失败: {e}")
                results[code] = False
        return results

    def get_kline(
        self,
        codes: Iterable[str],
        period: str = "1d",
        count: int = 30,
        fields: Optional[list] = None,
    ):
        """拉取 K 线 dict[code -> DataFrame]"""
        from xtquant import xtdata

        if fields is None:
            fields = ["open", "high", "low", "close", "volume", "amount"]
        norm = [self.normalize_code(c) for c in codes]
        return xtdata.get_market_data_ex(
            field_list=fields,
            stock_list=norm,
            period=period,
            count=count,
        )

    def get_tick(self, codes: Iterable[str]) -> dict:
        """拉取盘口 tick"""
        from xtquant import xtdata

        norm = [self.normalize_code(c) for c in codes]
        return xtdata.get_full_tick(norm)

    def subscribe_quote(
        self,
        code: str,
        callback: Callable[[dict], None],
        period: str = "tick",
    ) -> int:
        """订阅实时行情，回调返回 sub_id（>0 成功，<0 失败）"""
        from xtquant import xtdata

        norm = self.normalize_code(code)
        sub_id = xtdata.subscribe_quote(norm, period=period, callback=callback)
        return sub_id
