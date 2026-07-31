"""
sim/config_resolver.py — 统一配置、数据库路径和通知解析入口

QL-004: 所有模块必须通过此模块获取配置、DB路径和通知器。
不再允许各自读取 config/config.yaml、硬编码 DB 路径或多套 webhook helper。

设计原则:
  - 根 config.yaml + config.local.yaml 为唯一配置来源
  - QUANT_DB_PATH 经一个函数解析；测试必须显式注入临时路径
  - notifier/wecom_notifier.py 成为唯一企微实现
  - 旧源发弃用告警，不立即删除
  - 配置加载结果增加 schema 校验和 config_hash
"""

import hashlib
import json
import logging
import os
import warnings
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config.yaml"
_LOCAL_FILE = _PROJECT_ROOT / "config.local.yaml"

# ─── 弃用路径检测 ───
_DEPRECATED_CONFIG_PATHS = [
    _PROJECT_ROOT / "config" / "config.yaml",
    _PROJECT_ROOT / "vqlearn" / "config" / "portfolio.yaml",
]


def config_hash(cfg: dict) -> str:
    """计算配置的哈希值，用于审计和实验复现"""
    content = json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def resolve_db_path(override: Optional[str | Path] = None) -> Path:
    """统一数据库路径解析。

    优先级:
      1. 显式传入 override（测试注入）
      2. QUANT_DB_PATH 环境变量
      3. config.yaml 中的 database.path
      4. 默认 data/sim_live_mirror.db → data/sim.db

    测试必须通过 override 参数注入临时路径，不再依赖环境变量或默认路径。
    """
    if override:
        return Path(override)

    # 环境变量
    env_path = os.environ.get("QUANT_DB_PATH")
    if env_path:
        return Path(env_path)

    # 配置文件
    try:
        from sim.config import load_config
        cfg = load_config()
        cfg_path = cfg.get("database", {}).get("path")
        if cfg_path:
            return Path(cfg_path)
    except Exception:
        pass

    # 默认：优先 sim_live_mirror.db
    live_db = _PROJECT_ROOT / "data" / "sim_live_mirror.db"
    default_db = _PROJECT_ROOT / "data" / "sim.db"
    if live_db.exists():
        return live_db
    return default_db


def resolve_artifact_root() -> Path:
    """产物根目录。

    QUANT_ARTIFACT_ROOT 存在时用它（本机长期模拟隔离用 output/linux_sim），
    否则默认项目 output/。
    """
    env = (os.environ.get("QUANT_ARTIFACT_ROOT") or "").strip()
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _PROJECT_ROOT / "output"


def resolve_journal_dirs() -> tuple[Path, Path]:
    """台账落盘目录 (主路径, 镜像路径)。

    设了 QUANT_ARTIFACT_ROOT 时两者都落到 artifact/trade_journal，
    避免本机覆盖产机 pm/trade_journal。
    """
    if (os.environ.get("QUANT_ARTIFACT_ROOT") or "").strip():
        d = resolve_artifact_root() / "trade_journal"
        d.mkdir(parents=True, exist_ok=True)
        return d, d
    pm = _PROJECT_ROOT / "pm" / "trade_journal"
    mirror = _PROJECT_ROOT / "output" / "trade_journal"
    return pm, mirror


def resolve_wecom_webhook() -> Optional[str]:
    """统一企微 webhook URL 解析。

    优先级:
      1. WECOM_WEBHOOK 环境变量
      2. config.yaml / config.local.yaml 中 notifier.wecom_webhook 或 notify.wecom_webhook
      3. 返回 None（dry-run 模式）

    其他读取 webhook 的路径应迁移到使用此函数。
    """
    # 环境变量
    env_url = os.environ.get("WECOM_WEBHOOK")
    if env_url:
        return env_url

    # 配置文件
    try:
        from sim.config import load_config
        cfg = load_config()
        # 兼容两种 key: notifier.wecom_webhook 和 notify.wecom_webhook
        notifier_cfg = cfg.get("notifier", {})
        notify_cfg = cfg.get("notify", {})
        url = notifier_cfg.get("wecom_webhook") or notify_cfg.get("wecom_webhook")
        if url:
            return url
    except Exception:
        pass

    return None


def check_deprecated_configs() -> list[str]:
    """检测弃用的配置文件路径，返回警告列表。

    旧源: config/config.yaml, vqlearn/config/portfolio.yaml, 根目录硬编码
    这些不应再被使用，但暂时保留并发弃用告警。
    """
    warnings_found = []
    for dep_path in _DEPRECATED_CONFIG_PATHS:
        if dep_path.exists():
            msg = (
                f"⚠️ DEPRECATED: {dep_path.relative_to(_PROJECT_ROOT)} 仍存在。"
                f"请迁移到根目录 config.yaml + config.local.yaml。"
                f"此文件将在 QL-013 阶段删除。"
            )
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            warnings_found.append(str(dep_path))
            logger.warning(msg)
    return warnings_found


def validate_config(cfg: dict) -> list[str]:
    """Schema 校验 — 检查关键字段是否存在和合法。

    返回错误列表（空=校验通过）。
    缺失字段时报可定位错误，不静默使用危险默认值。
    """
    errors = []

    # accounts 必须存在
    if "accounts" not in cfg:
        errors.append("config missing 'accounts' section — cannot determine account settings")
    else:
        for key, acct in cfg.get("accounts", {}).items():
            if not isinstance(acct, dict):
                continue
            if "initial_cash" not in acct:
                errors.append(f"accounts.{key} missing 'initial_cash'")
            if "account_id" not in acct:
                errors.append(f"accounts.{key} missing 'account_id'")

    # risk 必须存在
    if "risk" not in cfg:
        errors.append("config missing 'risk' section — cannot enforce risk limits")
    else:
        risk = cfg["risk"]
        required_risk = ["max_position_pct", "max_total_positions", "stop_loss_pct"]
        for field in required_risk:
            if field not in risk:
                errors.append(f"risk.{field} missing — required for risk management")

    # broker.mode 必须是已知值
    mode = cfg.get("broker", {}).get("mode", "sim")
    if mode not in ("sim", "live", "qmt", "dry_run"):
        errors.append(f"broker.mode='{mode}' is not a recognized mode (sim/live/qmt/dry_run)")

    # 敏感字段只从 local 或环境变量读取
    # (只做信息性检查，不强求)

    return errors


def get_config_with_validation() -> tuple[dict, list[str], str]:
    """加载配置并校验，返回 (config, errors, hash)。

    典型用法:
        cfg, errors, cfg_hash = get_config_with_validation()
        if errors:
            logger.error("配置校验失败: %s", errors)
            raise SystemExit(1)
    """
    from sim.config import load_config
    cfg = load_config()
    errors = validate_config(cfg)
    h = config_hash(cfg)

    # 检测弃用配置
    dep_warnings = check_deprecated_configs()
    if dep_warnings:
        logger.warning("发现弃用配置文件: %s", dep_warnings)

    # 启动时打印最终模式（不打印凭据）
    mode = cfg.get("broker", {}).get("mode", "sim")
    logger.info(f"配置加载完成: mode={mode} config_hash={h} errors={len(errors)}")

    return cfg, errors, h
