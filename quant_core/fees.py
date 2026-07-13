"""
quant_core/fees.py — 日期生效的统一费用模型

QL-005: 保证回测、sim 和 QMT 审计使用同一费用口径。

设计要点:
  - 一个 FeeModel.calculate(side, amount, trade_date) 返回佣金、印花税、其他费用
  - 支持最低佣金和按日期生效的税率
  - A股规则:
    - 买入不收印花税，卖出收印花税
    - 2023-08-28 起印花税从 0.1% 降为 0.05%
    - 佣金双向收取，有最低佣金
    - 过户费 0.001% 双向收取（沪市）
  - 无IO副作用：不访问文件、网络或数据库
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from typing import Optional


@dataclass
class FeeBreakdown:
    """费用明细"""
    commission: float = 0.0       # 佣金
    stamp_tax: float = 0.0        # 印花税
    transfer_fee: float = 0.0     # 过户费
    total: float = 0.0           # 总费用
    estimated: bool = False       # 是否为估算（QMT实际费用不可得时）

    def __post_init__(self):
        self.total = self.commission + self.stamp_tax + self.transfer_fee


@dataclass
class FeeConfig:
    """费用配置"""
    commission_rate: float = 0.00025      # 佣金费率（万2.5）
    min_commission: float = 5.0           # 最低佣金（元）
    stamp_tax_rate_old: float = 0.001     # 2023-08-28前印花税率（千1）
    stamp_tax_rate_new: float = 0.0005    # 2023-08-28起印花税率（千0.5）
    stamp_tax_change_date: Date = field(
        default_factory=lambda: Date(2023, 8, 28)
    )
    transfer_fee_rate: float = 0.00001    # 过户费率（万0.1，沪市）
    transfer_fee_enabled: bool = True     # 是否计算过户费


class FeeModel:
    """统一费用模型 — 同一成交在各路径的费用结果完全一致。

    用法:
        model = FeeModel()  # 使用默认A股费率
        fees = model.calculate(side="SELL", amount=10000.0, trade_date=Date(2024, 1, 15))
        print(fees.total)  # 5.60 (佣金2.5 + 印花税5.0 + 过户费0.1 → 实际5.0+0.1)
    """

    def __init__(self, config: Optional[FeeConfig] = None):
        self._config = config or FeeConfig()

    def calculate(
        self,
        side: str,
        amount: float,
        trade_date: Optional[Date] = None,
        exchange: str = "SH",
        estimated: bool = False,
    ) -> FeeBreakdown:
        """计算费用

        :param side: "BUY" or "SELL"
        :param amount: 成交金额
        :param trade_date: 交易日期（决定印花税率）
        :param exchange: 交易所 "SH"/"SZ"（过户费仅沪市）
        :param estimated: 是否为估算值
        :return: FeeBreakdown
        """
        if amount <= 0:
            return FeeBreakdown(estimated=estimated)

        # 佣金 — 双向收取，有最低
        commission = max(amount * self._config.commission_rate, self._config.min_commission)

        # 印花税 — 仅卖出，按日期生效
        stamp_tax = 0.0
        if side.upper() == "SELL":
            stamp_rate = self._get_stamp_tax_rate(trade_date)
            stamp_tax = amount * stamp_rate

        # 过户费 — 双向收取（沪市）
        transfer_fee = 0.0
        if self._config.transfer_fee_enabled and exchange.upper() in ("SH", "SSE"):
            transfer_fee = amount * self._config.transfer_fee_rate

        return FeeBreakdown(
            commission=round(commission, 2),
            stamp_tax=round(stamp_tax, 2),
            transfer_fee=round(transfer_fee, 2),
            estimated=estimated,
        )

    def _get_stamp_tax_rate(self, trade_date: Optional[Date]) -> float:
        """根据交易日期返回印花税率"""
        if trade_date is None:
            return self._config.stamp_tax_rate_new  # 默认用新税率
        if trade_date < self._config.stamp_tax_change_date:
            return self._config.stamp_tax_rate_old
        return self._config.stamp_tax_rate_new

    @staticmethod
    def from_config(cfg: dict) -> "FeeModel":
        """从配置字典构建 FeeModel"""
        fees_cfg = cfg.get("fees", {})
        fee_config = FeeConfig(
            commission_rate=float(fees_cfg.get("commission_rate", 0.00025)),
            min_commission=float(fees_cfg.get("min_commission", 5.0)),
            stamp_tax_rate_new=float(fees_cfg.get("stamp_tax_rate", 0.0005)),
            transfer_fee_rate=float(fees_cfg.get("transfer_fee_rate", 0.00001)),
        )
        return FeeModel(config=fee_config)
