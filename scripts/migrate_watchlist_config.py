#!/usr/bin/env python
"""
scripts/migrate_watchlist_config.py — config.yaml 观察池结构迁移工具

功能：
  1. 读取现有 config.yaml 中的 watchlist（扁平结构）
  2. 全部归类为 user_manual（用户手动指定）
  3. 初始化 auto_discovered 为空
  4. 备份原 config.yaml → config.yaml.bak.YYYYMMDD_HHMMSS
  5. 写入新结构
  6. 初始化 watchlist_history 表（迁移现有数据）

使用：
  python scripts/migrate_watchlist_config.py [--dry-run]
"""
import sys
import shutil
from pathlib import Path
from datetime import datetime, date
import sqlite3
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIG_FILE = ROOT / "config.yaml"
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

try:
    import yaml
except ImportError:
    print("❌ 需要安装 pyyaml: pip install pyyaml")
    sys.exit(1)


def backup_config():
    """备份现有 config.yaml"""
    if not CONFIG_FILE.exists():
        print("⚠️ config.yaml 不存在，跳过备份")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = CONFIG_FILE.with_suffix(f".yaml.bak.{timestamp}")
    shutil.copy2(CONFIG_FILE, backup_path)
    print(f"✓ 已备份 config.yaml → {backup_path.name}")
    return backup_path


def load_current_config():
    """加载现有配置"""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def migrate_watchlist_structure(cfg):
    """迁移观察池结构：扁平 → 分层"""
    old_watchlist = cfg.get("watchlist", {})
    if not old_watchlist:
        print("⚠️ 现有 watchlist 为空，无需迁移")
        return cfg
    
    # 检查是否已经是新结构（有 user_manual / auto_discovered 键）
    if "user_manual" in old_watchlist or "auto_discovered" in old_watchlist:
        print("✓ 观察池已是新结构，跳过迁移")
        return cfg
    
    # 迁移：全部归类为 user_manual
    new_watchlist = {
        "user_manual": {},
        "auto_discovered": {}
    }
    
    migrated_count = 0
    for code, body in old_watchlist.items():
        if code in ("user_manual", "auto_discovered"):  # 跳过新结构键（不应存在）
            continue
        # 补充缺失字段
        if "source" not in body:
            body["source"] = "legacy_migration"
        if "added_at" not in body:
            body["added_at"] = date.today().isoformat()
        new_watchlist["user_manual"][code] = body
        migrated_count += 1
    
    cfg["watchlist"] = new_watchlist
    print(f"✓ 迁移 {migrated_count} 只股票到 user_manual")
    return cfg


def write_new_config(cfg):
    """写回 config.yaml（保留注释需要手动处理，这里直接覆盖）"""
    # 添加注释块（手动拼接，因为 PyYAML 不保留注释）
    header = """# config.yaml — 量化交易系统配置（2026-05-25 观察池分层重构）
#
# 推荐用法：把账户敏感配置放到 config.local.yaml（已加入 .gitignore），
# config.local.yaml 会覆盖本文件的同名字段。
#
# ========== 观察池（分层管理）==========
# watchlist.user_manual       : 用户手动指定（永久，除非用户明确删除）
# watchlist.auto_discovered   : 系统自动发现（有生命周期，自动淘汰）
#

"""
    # 序列化 YAML
    yaml_str = yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # 写回文件
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(yaml_str)
    
    print(f"✓ 已写入新结构 config.yaml")


def init_watchlist_history(cfg):
    """初始化 watchlist_history 表（写入现有观察池数据）"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # 执行 SQL migration
    migration_sql = (ROOT / "data" / "migrations" / "001_watchlist_history.sql").read_text(encoding="utf-8")
    c.executescript(migration_sql)
    print("✓ 创建 watchlist_history 表")
    
    # 插入现有 user_manual 数据
    user_manual = cfg.get("watchlist", {}).get("user_manual", {})
    today = date.today().isoformat()
    inserted = 0
    
    for code, body in user_manual.items():
        name = body.get("name", "")
        added_at = body.get("added_at", today)
        source = body.get("source", "user")
        reason = body.get("added_reason", "迁移自旧配置")
        tags = body.get("tags", [])
        
        metadata = json.dumps({"tags": tags, "source": source}, ensure_ascii=False)
        
        try:
            c.execute("""
                INSERT OR IGNORE INTO watchlist_history
                (code, name, category, added_at, added_by, added_reason, metadata)
                VALUES (?, ?, 'user_manual', ?, ?, ?, ?)
            """, (code, name, added_at, source, reason, metadata))
            inserted += c.rowcount
        except sqlite3.IntegrityError:
            pass  # 已存在，跳过
    
    conn.commit()
    conn.close()
    print(f"✓ 初始化 watchlist_history: {inserted} 条记录")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="config.yaml 观察池结构迁移工具")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不写入文件）")
    args = parser.parse_args()
    
    print("=== config.yaml 观察池迁移工具 ===\n")
    
    # 1. 备份
    if not args.dry_run:
        backup_config()
    else:
        print("[DRY RUN] 跳过备份")
    
    # 2. 加载配置
    cfg = load_current_config()
    if not cfg:
        print("❌ config.yaml 为空或不存在")
        return 1
    
    # 3. 迁移结构
    cfg = migrate_watchlist_structure(cfg)
    
    # 4. 写入新配置
    if not args.dry_run:
        write_new_config(cfg)
    else:
        print("[DRY RUN] 跳过写入 config.yaml")
        print("\n预览新结构:")
        print(yaml.dump(cfg.get("watchlist", {}), allow_unicode=True, indent=2))
    
    # 5. 初始化数据库
    if not args.dry_run:
        init_watchlist_history(cfg)
    else:
        print("[DRY RUN] 跳过数据库初始化")
    
    print("\n✅ 迁移完成！")
    print("\n后续步骤:")
    print("  1. 检查 config.yaml 结构是否正确")
    print("  2. 运行 python sim/portfolio.py 验证加载正常")
    print("  3. 部署 scripts/intraday_scanner.py 和 scripts/cleanup_watchlist.py")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
