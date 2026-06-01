"""
Agent 助手：封装常用的 PM/量化操作，让 Agent 直接调 exec
======================================================================
用法（Agent 直接 exec 这些命令）：

1. 创建需求：
   python scripts/agent_helper.py create_story "标题" --desc "描述" --priority P1

2. 创建 Bug：
   python scripts/agent_helper.py create_bug "标题" --desc "描述" --priority S1

3. 更新任务状态：
   python scripts/agent_helper.py update REQ-XXX --status done

4. 列出待处理任务：
   python scripts/agent_helper.py list_pending

5. 读取今日持仓：
   python scripts/agent_helper.py show_positions

6. 读取今日交易：
   python scripts/agent_helper.py show_trades
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "pm.db"
SIM_DB = ROOT / "data" / "sim_live_mirror.db"

sys.path.insert(0, str(ROOT))
from sim.precision import fmt_cost, fmt_price


def ensure_task_claim_columns(conn):
    """确保 tasks 表具备轻量认领字段（兼容旧库，幂等）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "assigned_to" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_to TEXT")
    if "work_notes" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN work_notes TEXT")


def pick_and_work(worker="agent", task_id=None):
    """原子认领 1 个 pending 任务，标记为 in_progress 并写 assigned_to。

    用法：python scripts/agent_helper.py pick_and_work --worker worker-1 [--task-id BUG-001]
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_task_claim_columns(conn)
        if task_id:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=? AND status='pending'",
                (task_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status='pending'
                ORDER BY CASE priority
                    WHEN 'S0' THEN 0 WHEN 'P0' THEN 0
                    WHEN 'S1' THEN 1 WHEN 'P1' THEN 1
                    WHEN 'S2' THEN 2 WHEN 'P2' THEN 2
                    WHEN 'S3' THEN 3 WHEN 'P3' THEN 3
                    ELSE 9 END,
                    created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return "NO_PENDING_TASK"

        cur = conn.execute(
            """
            UPDATE tasks
               SET status='in_progress', assigned_to=?, updated_at=?,
                   work_notes=COALESCE(work_notes || char(10), '') || ?
             WHERE id=? AND status='pending'
            """,
            (worker, now, f"[{now}] claimed by {worker}", row["id"]),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return "CLAIM_RACE_LOST"
        conn.execute("COMMIT")
        return (f"CLAIMED {row['id']} [{row['priority']}] {row['title']}\n"
                f"description: {row['description'] or ''}")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def create_story(title, desc="", priority="P1"):
    """创建需求故事"""
    import subprocess
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pm_cli.py"),
        "create", "story",
        title,
        "--desc", desc,
        "--priority", priority
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() or result.stderr.strip()


def create_bug(title, desc="", priority="S1"):
    """创建 Bug"""
    import subprocess
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pm_cli.py"),
        "create", "bug",
        title,
        "--desc", desc,
        "--priority", priority
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() or result.stderr.strip()


def update_task(task_id, **kwargs):
    """更新任务"""
    import subprocess
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pm_cli.py"),
        "update", task_id
    ]
    for k, v in kwargs.items():
        cmd.append(f"--{k}")
        cmd.append(v)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() or result.stderr.strip()


def list_pending():
    """列出待处理任务"""
    import subprocess
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pm_cli.py"),
        "list",
        "--status", "pending",
        "--type", "story"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() or result.stderr.strip()


def show_positions():
    """显示今日持仓"""
    conn = sqlite3.connect(SIM_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT stock_code, stock_name, quantity, avg_cost, current_price,
               market_value, pnl, pnl_pct
        FROM sim_positions
        WHERE quantity > 0
        ORDER BY market_value DESC
    """)
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        return "（无持仓）"
    
    lines = ["📊 当前持仓："]
    for r in rows:
        pnl_sign = "+" if r["pnl"] >= 0 else ""
        lines.append(
            f"  {r['stock_name']}({r['stock_code']}) "
            f"{r['quantity']}股 @成本{fmt_cost(r['avg_cost'])} "
            f"现值{fmt_price(r['current_price'])} "
            f"{pnl_sign}{r['pnl_pct']*100:.1f}%"
        )
    return "\n".join(lines)


def show_trades(date=None):
    """显示交易记录"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(SIM_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT trade_date, stock_code, stock_name, direction, price, quantity, amount
        FROM sim_trades
        WHERE trade_date LIKE ?
        ORDER BY trade_date DESC, id DESC
    """, (f"{date}%",))
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        return f"（{date} 无交易）"
    
    lines = [f"📊 {date} 交易记录："]
    for r in rows:
        lines.append(
            f"  {r['trade_date']} {r['direction']} "
            f"{r['stock_name']}({r['stock_code']}) "
            f"{r['quantity']}股 @ {fmt_price(r['price'])} "
            f"金额{r['amount']:.0f}元"
        )
    return "\n".join(lines)


# CLI 入口
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    action = sys.argv[1]
    
    if action == "pick_and_work":
        worker = "agent"
        task_id = None
        if "--worker" in sys.argv:
            worker = sys.argv[sys.argv.index("--worker") + 1]
        if "--task-id" in sys.argv:
            task_id = sys.argv[sys.argv.index("--task-id") + 1]
        print(pick_and_work(worker=worker, task_id=task_id))

    elif action == "create_story":
        title = sys.argv[2] if len(sys.argv) > 2 else "未命名需求"
        desc = ""
        priority = "P1"
        if "--desc" in sys.argv:
            desc = sys.argv[sys.argv.index("--desc") + 1]
        if "--priority" in sys.argv:
            priority = sys.argv[sys.argv.index("--priority") + 1]
        print(create_story(title, desc, priority))
    
    elif action == "create_bug":
        title = sys.argv[2] if len(sys.argv) > 2 else "未命名Bug"
        desc = ""
        priority = "S1"
        if "--desc" in sys.argv:
            desc = sys.argv[sys.argv.index("--desc") + 1]
        if "--priority" in sys.argv:
            priority = sys.argv[sys.argv.index("--priority") + 1]
        print(create_bug(title, desc, priority))
    
    elif action == "update":
        task_id = sys.argv[2]
        kwargs = {}
        i = 3
        while i < len(sys.argv):
            if sys.argv[i].startswith("--"):
                key = sys.argv[i][2:]
                val = sys.argv[i+1] if i+1 < len(sys.argv) else ""
                kwargs[key] = val
                i += 2
            else:
                i += 1
        print(update_task(task_id, **kwargs))
    
    elif action == "list_pending":
        print(list_pending())
    
    elif action == "show_positions":
        print(show_positions())
    
    elif action == "show_trades":
        date = sys.argv[2] if len(sys.argv) > 2 else None
        print(show_trades(date))
    
    else:
        print(f"未知操作: {action}")
        print(__doc__)
        sys.exit(1)
