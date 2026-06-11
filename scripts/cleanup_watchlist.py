#!/usr/bin/env python
"""
scripts/cleanup_watchlist.py — 自动观察池淘汰器

功能：
  - 每日盘前运行（8:00，在 morning_scanner 之前）
  - 检查 watchlist.auto_discovered 中的股票
  - 执行淘汰规则：
    1. 无触发淘汰：加入 N 天（默认 7 天）未触发任何阈值
    2. 趋势破位淘汰：已触发 trend_break 规则
    3. 低分衰减淘汰：discovery_score < 60 且 3 天无触发
  - 更新 config.yaml + watchlist_history
  - 推送淘汰报告到企微

使用：
  python scripts/cleanup_watchlist.py [--no-webhook] [--dry-run]

计划任务：
  每日 8:00 运行
"""
import sys
import json
import logging
import argparse
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = ROOT / "data" / "sim_live_mirror.db"
CONFIG_FILE = ROOT / "config.yaml"
OUTPUT_DIR = ROOT / "output" / "cleanup_logs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ====================================================================
#  配置加载
# ====================================================================
try:
    import yaml
except ImportError:
    logger.error("需要安装 pyyaml: pip install pyyaml")
    sys.exit(1)

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def save_config(cfg):
    """保存配置（带文件锁）"""
    try:
        import fcntl
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except ImportError:
        # Windows 环境没有 fcntl，直接写（风险：并发冲突）
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

# ====================================================================
#  Webhook
# ====================================================================
def _load_webhook():
    try:
        local_cfg = ROOT / "config.local.yaml"
        if local_cfg.exists():
            d = yaml.safe_load(local_cfg.read_text(encoding="utf-8"))
            return (d or {}).get("notifier", {}).get("wecom_webhook", "")
    except Exception:
        pass
    return ""

WEBHOOK_URL = _load_webhook()

def push_webhook(content: str) -> bool:
    if not WEBHOOK_URL:
        logger.warning("未配置 webhook URL")
        return False
    body = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}).encode("utf-8")
    req = urllib.request.Request(WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        logger.error(f"webhook 推送失败: {e}")
        return False

# ====================================================================
#  数据库操作
# ====================================================================
def get_alert_history(code):
    """从 watchlist_history 获取该股票的告警历史"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    row = c.execute("""
        SELECT last_alert_at, alert_count
        FROM watchlist_history
        WHERE code = ? AND category = 'auto_discovered' AND removed_at IS NULL
        ORDER BY added_at DESC LIMIT 1
    """, (code,)).fetchone()
    conn.close()
    
    if row:
        return {
            'last_alert_at': row[0],
            'alert_count': row[1]
        }
    return None

def mark_removed_in_db(code, reason):
    """标记为已移除（写入 removed_at + removed_reason）"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute("""
        UPDATE watchlist_history
        SET removed_at = ?, removed_reason = ?
        WHERE code = ? AND category = 'auto_discovered' AND removed_at IS NULL
    """, (today, reason, code))
    conn.commit()
    conn.close()
    logger.info(f"  ✓ 数据库标记 {code} 已移除 (reason={reason})")

# ====================================================================
#  淘汰规则
# ====================================================================
def should_remove(code, config_entry):
    """
    判断是否应该移除该股票
    
    返回: (should_remove: bool, reason: str)
    """
    today = date.today()
    
    # 读取元数据
    added_at_str = config_entry.get('added_at')
    if not added_at_str:
        logger.warning(f"  {code} 缺少 added_at 字段，跳过")
        return False, ""
    
    try:
        added_at = date.fromisoformat(added_at_str)
    except ValueError:
        logger.warning(f"  {code} added_at 格式错误: {added_at_str}")
        return False, ""
    
    days_since_added = (today - added_at).days
    discovery_score = config_entry.get('discovery_score', 0)
    max_inactive_days = config_entry.get('max_inactive_days', 7)
    
    # 从数据库读取告警历史
    hist = get_alert_history(code)
    last_alert_at = None
    alert_count = 0
    
    if hist:
        last_alert_at_str = hist['last_alert_at']
        alert_count = hist['alert_count']
        if last_alert_at_str:
            try:
                last_alert_at = date.fromisoformat(last_alert_at_str)
            except ValueError:
                pass
    
    # 规则1: 无触发淘汰（N 天无告警）
    if last_alert_at:
        days_since_alert = (today - last_alert_at).days
    else:
        days_since_alert = days_since_added  # 从未触发，用加入天数
    
    if days_since_alert >= max_inactive_days:
        return True, f"inactive_{days_since_alert}_days"
    
    # 规则2: 低分衰减淘汰（score < 60 且 3 天无触发）
    if discovery_score < 60 and days_since_alert >= 3:
        return True, "low_score_inactive"
    
    # 规则3: 趋势破位淘汰（需要从最近一次告警消息判断，这里简化处理）
    # 实际应该由 portfolio_alert.py 在触发 trend_break 时主动标记
    # 这里暂不实现自动检测（需要实时行情）
    
    return False, ""

# ====================================================================
#  主流程
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="自动观察池淘汰器")
    parser.add_argument("--no-webhook", action="store_true", help="不推送企微")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不写入 config.yaml）")
    args = parser.parse_args()
    
    now = datetime.now()
    today = date.today()
    logger.info(f"=== 观察池淘汰器 开始 {now.strftime('%Y-%m-%d %H:%M')} ===")
    
    # 加载配置
    cfg = load_config()
    auto_discovered = cfg.get("watchlist", {}).get("auto_discovered", {})
    
    if not auto_discovered:
        print("✓ auto_discovered 为空，无需淘汰")
        logger.info("auto_discovered 为空，退出")
        return 0
    
    logger.info(f"当前 auto_discovered: {len(auto_discovered)} 只")
    
    # 遍历检查
    to_remove = []
    
    for code, entry in auto_discovered.items():
        should_rm, reason = should_remove(code, entry)
        if should_rm:
            name = entry.get('name', code)
            to_remove.append({
                'code': code,
                'name': name,
                'reason': reason,
                'added_at': entry.get('added_at'),
                'score': entry.get('discovery_score', 0),
            })
            logger.info(f"  标记移除: {code} {name} (reason={reason})")
    
    logger.info(f"需要移除: {len(to_remove)} 只")
    
    # 执行移除
    if to_remove:
        if not args.dry_run:
            for item in to_remove:
                # 从 config.yaml 删除
                if item['code'] in auto_discovered:
                    del auto_discovered[item['code']]
                
                # 数据库标记
                mark_removed_in_db(item['code'], item['reason'])
            
            # 保存配置
            cfg["watchlist"]["auto_discovered"] = auto_discovered
            save_config(cfg)
            logger.info(f"✓ config.yaml 已更新")
        else:
            logger.info("[DRY RUN] 跳过写入 config.yaml 和数据库")
        
        # 保存历史
        out_file = OUTPUT_DIR / f"{today.isoformat()}_cleanup.json"
        out_file.write_text(json.dumps({
            "date": today.isoformat(),
            "removed": to_remove,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"已保存 {out_file}")
        
        # 推送企微
        if not args.no_webhook and not args.dry_run:
            md = generate_markdown(today, to_remove)
            if push_webhook(md):
                logger.info("✓ 企微推送成功")
        
        # 打印
        print(f"\n🧹 观察池淘汰 ({today.isoformat()}) | 移除 {len(to_remove)} 只\n")
        for item in to_remove:
            print(f"  {item['code']} {item['name']:8s} | {item['reason']:20s} | "
                  f"加入日期={item['added_at']} score={item['score']:.0f}")
    else:
        print(f"✓ {today.isoformat()} 无需淘汰")
        logger.info("无需淘汰")
    
    logger.info(f"=== 观察池淘汰器 结束 ===\n")
    return 0


def generate_markdown(today, removed):
    """生成企微 Markdown 消息"""
    md = []
    md.append(f"# 🧹 观察池淘汰 ({today.year}/{today.month}/{today.day})")
    md.append("")
    md.append(f"**移除** {len(removed)} 只:")
    md.append("")
    for i, item in enumerate(removed, 1):
        reason_map = {
            "inactive_7_days": "7天无触发",
            "inactive_10_days": "10天无触发",
            "low_score_inactive": "低分+无触发",
            "trend_broken": "趋势破位",
        }
        reason_text = reason_map.get(item['reason'], item['reason'])
        line = f"{i}. **{item['name']}** ({item['code']}) | {reason_text}"
        md.append(line)
        md.append(f"  - 加入日期: {item['added_at']} | 评分: {item['score']:.0f}")
    md.append("")
    md.append("> ⚠️ 系统自动淘汰，用户手动观察池不受影响。")
    return "\n".join(md)


if __name__ == "__main__":
    sys.exit(main())
