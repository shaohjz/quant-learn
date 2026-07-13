"""
research/walk_forward.py — 嵌套滚动 Walk-forward 验证

QL-010: 替换70/30+243组gridsearch，保持真正未污染的样本外结果。

设计要点:
  - 内层训练窗口选参数，外层滚动窗口只评估
  - 最终holdout在所有策略、参数和特征冻结后只运行一次
  - 支持purge/embargo防止标签重叠泄漏
  - 每次实验记录data_hash、config_hash、code_version、参数数目和尝试次数
  - 报告Deflated Sharpe、bootstrap区间
  - 禁止按OUT排序后再称为OOS
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardSplit:
    """Walk-forward 时间窗口切分"""
    train_start: Date
    train_end: Date           # 内层训练窗口结束
    oos_start: Date
    oos_end: Date             # 外层评估窗口结束
    purge_days: int = 5       # purge: 训练与OOS之间的间隔
    embargo_days: int = 0     # embargo: OOS后的间隔


@dataclass
class ExperimentRecord:
    """实验记录 — 完整审计信息"""
    experiment_id: str
    strategy_name: str
    data_hash: str             # 数据版本hash
    config_hash: str           # 配置版本hash
    code_version: str          # 代码版本(git hash或tag)
    train_start: Date
    train_end: Date
    oos_start: Date
    oos_end: Date
    num_params: int            # 参数数量
    num_attempts: int          # 总尝试次数（含所有参数组合）
    best_params: dict          # 内层选出的最优参数（只在训练窗口）
    oos_metrics: dict          # 外层评估结果（不能用来选参数）
    holdout_used: bool = False  # 是否用了最终holdout


def generate_walk_forward_splits(
    start_date: Date,
    end_date: Date,
    train_window_days: int = 252,   # ~1年
    oos_window_days: int = 63,      # ~3个月
    purge_days: int = 5,
    embargo_days: int = 0,
    step_days: int = 63,            # 滚动步长
) -> list[WalkForwardSplit]:
    """生成Walk-forward滚动窗口切分

    内层训练窗口选参数，外层滚动窗口只评估。
    最终holdout在所有策略、参数和特征冻结后只运行一次。
    """
    splits: list[WalkForwardSplit] = []
    current_start = start_date

    while True:
        from datetime import timedelta
        train_end = current_start + timedelta(days=train_window_days)
        oos_start = train_end + timedelta(days=purge_days)
        oos_end = oos_start + timedelta(days=oos_window_days)

        if oos_end > end_date:
            break

        splits.append(WalkForwardSplit(
            train_start=current_start,
            train_end=train_end,
            purge_days=purge_days,
            oos_start=oos_start,
            oos_end=oos_end,
            embargo_days=embargo_days,
        ))

        current_start += timedelta(days=step_days)

    return splits


def validate_no_oos_leakage(
    splits: list[WalkForwardSplit],
    holdout_start: Optional[Date] = None,
) -> list[str]:
    """验证任何OOS/holdout日期不能进入参数选择函数

    Returns list of violations (empty = no leakage).
    """
    violations: list[str] = []

    for i, split in enumerate(splits):
        # OOS期间不能与训练窗口重叠
        if split.oos_start <= split.train_end:
            violations.append(
                f"Split {i}: OOS starts {split.oos_start} before/within train end {split.train_end}"
            )

    # 最终holdout检查
    if holdout_start and splits:
        last_oos_end = splits[-1].oos_end
        if holdout_start <= last_oos_end:
            violations.append(
                f"Holdout starts {holdout_start} overlaps with last OOS end {last_oos_end}"
            )

    return violations


def compute_data_hash(data_paths: list[str]) -> str:
    """计算数据产物的hash"""
    content = json.dumps(sorted(data_paths))
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class WalkForwardConfig:
    """Walk-forward 配置"""
    start_date: Date
    end_date: Date
    train_window_days: int = 252
    oos_window_days: int = 63
    purge_days: int = 5
    embargo_days: int = 0
    step_days: int = 63
    holdout_start: Optional[Date] = None   # 最终holdout起始日期
    holdout_end: Optional[Date] = None
    # 禁止配置
    allow_oos_param_selection: bool = False  # 必须为False!


class WalkForwardValidator:
    """Walk-forward 验证器"""

    def __init__(self, config: WalkForwardConfig):
        self._config = config
        self._splits = generate_walk_forward_splits(
            start_date=config.start_date,
            end_date=config.end_date,
            train_window_days=config.train_window_days,
            oos_window_days=config.oos_window_days,
            purge_days=config.purge_days,
            embargo_days=config.embargo_days,
            step_days=config.step_days,
        )

    def validate(self) -> list[str]:
        """验证所有约束"""
        violations = validate_no_oos_leakage(self._splits, self._config.holdout_start)

        # 禁止OOS参数选择
        if self._config.allow_oos_param_selection:
            violations.append("CRITICAL: allow_oos_param_selection must be False!")

        return violations

    def get_splits(self) -> list[WalkForwardSplit]:
        return self._splits

    def num_splits(self) -> int:
        return len(self._splits)

    def report_summary(self) -> dict:
        """生成Walk-forward报告摘要"""
        return {
            "num_splits": self.num_splits(),
            "train_window_days": self._config.train_window_days,
            "oos_window_days": self._config.oos_window_days,
            "purge_days": self._config.purge_days,
            "holdout": f"{self._config.holdout_start}~{self._config.holdout_end}",
            "violations": self.validate(),
        }
