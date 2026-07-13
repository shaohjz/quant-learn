"""
research/experiment_registry.py — 实验注册与审计

QL-010: 每次实验记录data_hash、config_hash、code_version、参数数目和尝试次数。
禁止按OUT排序后再称为OOS。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as Date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExperimentEntry:
    """实验注册条目"""
    experiment_id: str
    strategy_name: str
    data_hash: str
    config_hash: str
    code_version: str
    created_at: datetime = field(default_factory=datetime.now)
    num_params: int = 0
    num_attempts: int = 0
    train_period: str = ""
    oos_period: str = ""
    holdout_used: bool = False
    oos_metrics: dict = field(default_factory=dict)
    best_params: dict = field(default_factory=dict)
    # 多重检验信息
    deflated_sharpe: Optional[float] = None
    bootstrap_ci_lower: Optional[float] = None
    bootstrap_ci_upper: Optional[float] = None
    pbo: Optional[float] = None  # Probability of Backtest Overfitting
    status: str = "registered"


class ExperimentRegistry:
    """实验注册表 — 记录所有尝试和结果

    禁止只展示Top N — 必须同时展示全部窗口。
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self._path = registry_path
        self._entries: list[ExperimentEntry] = []
        if self._path and self._path.exists():
            self._load()

    def register(self, entry: ExperimentEntry) -> None:
        """注册一个实验"""
        self._entries.append(entry)
        logger.info(f"Registered experiment {entry.experiment_id}: {entry.strategy_name}")
        self._save()

    def get_all(self) -> list[ExperimentEntry]:
        """获取所有实验（包括失败的）"""
        return self._entries

    def get_by_strategy(self, strategy_name: str) -> list[ExperimentEntry]:
        """按策略名获取"""
        return [e for e in self._entries if e.strategy_name == strategy_name]

    def get_holdout_experiments(self) -> list[ExperimentEntry]:
        """获取使用最终holdout的实验"""
        return [e for e in self._entries if e.holdout_used]

    def validate_no_oos_param_selection(self) -> list[str]:
        """验证没有实验用OOS来选参数"""
        violations = []
        for e in self._entries:
            if e.status == "oos_param_selected":
                violations.append(
                    f"Experiment {e.experiment_id}: parameters selected on OOS data!"
                )
        return violations

    def _save(self) -> None:
        if self._path:
            data = [
                {
                    "experiment_id": e.experiment_id,
                    "strategy_name": e.strategy_name,
                    "data_hash": e.data_hash,
                    "config_hash": e.config_hash,
                    "code_version": e.code_version,
                    "num_params": e.num_params,
                    "num_attempts": e.num_attempts,
                    "status": e.status,
                    "holdout_used": e.holdout_used,
                    "oos_metrics": e.oos_metrics,
                }
                for e in self._entries
            ]
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            self._entries.append(ExperimentEntry(**d))

    def mark_legacy(self, strategy_name: str, note: str = "") -> None:
        """标记旧实验为legacy（探索性、不可部署）"""
        for e in self.get_by_strategy(strategy_name):
            e.status = "legacy"
            logger.warning(f"Marked {e.experiment_id} as legacy: {note}")
        self._save()
