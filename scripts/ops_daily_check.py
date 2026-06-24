#!/usr/bin/env python3
"""
scripts/ops_daily_check.py — 运维 Agent 每日巡检

每天 8:00 由 cron 调用，检查以下服务状态：
1. PM Web 服务（8080端口）
2. 数据源（baostock、akshare 等）
3. 模拟账户状态
4. 磁盘空间
5. 计划任务状态

输出到 output/ops_daily_check.log，异常时推送企微通知。
"""
import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / "output" / "ops_daily_check.log"
RESULT_FILE = ROOT / "output" / "ops_daily_check_result.json"

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")
    print(f"{ts} {msg}")

def check_pm_service() -> tuple[bool, str]:
    """检查 PM Web 服务"""
    for port in [8080]:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="HEAD")
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status < 500:
                return True, f"PM 服务正常 (端口 {port})"
        except Exception as e:
            continue
    return False, f"PM 服务无响应 (端口 8080)"

def check_datasources() -> tuple[bool, str]:
    """检查数据源"""
    issues = []
    # 检查 baostock
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            bs.logout()
        else:
            issues.append(f"baostock 登录失败: {lg.error_msg}")
    except Exception as e:
        issues.append(f"baostock 异常: {e}")
    
    # 检查数据库
    db_path = ROOT / "data" / "sim_live_mirror.db"
    if not db_path.exists():
        issues.append(f"数据库不存在: {db_path}")
    else:
        size_mb = db_path.stat().st_size / 1024 / 1024
        if size_mb > 500:
            issues.append(f"数据库过大: {size_mb:.0f}MB")
    
    if issues:
        return False, "; ".join(issues)
    return True, "数据源正常"

def check_account() -> tuple[bool, str]:
    """检查模拟账户状态"""
    try:
        import sqlite3
        conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
        conn.row_factory = sqlite3.Row
        acct = conn.execute("SELECT * FROM sim_account WHERE id = 1").fetchone()
        conn.close()
        if not acct:
            return False, "模拟账户不存在"
        cash = float(acct["cash"])
        total = float(acct["total_value"])
        return True, f"账户正常: 现金¥{cash:,.0f}, 总资产¥{total:,.0f}"
    except Exception as e:
        return False, f"账户检查异常: {e}"

def check_scheduled_tasks() -> tuple[bool, str]:
    """检查关键计划任务状态"""
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST", "/v"],
            capture_output=True, text=True, timeout=30
        )
        lines = result.stdout.split('\n')
        issues = []
        ok_tasks = []
        for task_name in ["QuantLearn_AdvisorIntraday", "QuantLearn_AdvisorReview", 
                          "QuantLearn_PM_Watchdog", "QuantLearn_DailyPM_Workflow",
                          "QuantLearnDashboard", "QuantLearn_OpsDailyCheck",
                          "QuantLearn_MorningScanner", "QuantLearn_PortfolioAlert"]:
            found = False
            for i, line in enumerate(lines):
                if task_name in line:
                    found = True
                    # 检查后面几行是否有 Disabled
                    for j in range(i, min(i+10, len(lines))):
                        if "Disabled" in lines[j]:
                            issues.append(f"{task_name} 已禁用")
                            break
                    else:
                        ok_tasks.append(task_name)
                    break
            if not found:
                issues.append(f"{task_name} 未找到")
        
        if issues:
            return False, f"关键任务正常: {len(ok_tasks)}, 异常: {len(issues)}; " + "; ".join(issues)
        return True, f"所有 {len(ok_tasks)} 个关键计划任务正常"
    except Exception as e:
        return False, f"计划任务检查异常: {e}"

def check_disk_space() -> tuple[bool, str]:
    """检查磁盘空间"""
    try:
        result = subprocess.run(
            ["wmic", "logicaldisk", "where", "drivetype=3", "get", "deviceid,freespace,size"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l.strip() for l in result.stdout.split('\n') if l.strip()]
        issues = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 3:
                free = int(parts[1]) / 1024 / 1024 / 1024
                total = int(parts[2]) / 1024 / 1024 / 1024
                pct = free / total * 100
                if pct < 10:
                    issues.append(f"{parts[0]} 剩余空间不足: {free:.1f}GB/{total:.0f}GB ({pct:.0f}%)")
        if issues:
            return False, "; ".join(issues)
        return True, f"磁盘空间正常 (C盘剩余 {free:.1f}GB/{total:.0f}GB)"
    except Exception as e:
        return False, f"磁盘检查异常: {e}"

def push_alert(message: str):
    """推送告警到企微"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        webhook = (cfg.get('notify') or {}).get('wecom_webhook', '')
        if webhook:
            body = json.dumps({"msgtype": "text", "text": {"content": message}}).encode("utf-8")
            req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

def main():
    log("=" * 60)
    log("运维 Agent 每日巡检开始")
    
    checks = {
        "pm_service": check_pm_service,
        "datasource": check_datasources,
        "account": check_account,
        "scheduled_tasks": check_scheduled_tasks,
        "disk_space": check_disk_space,
    }
    
    results = {}
    all_ok = True
    for name, check_fn in checks.items():
        try:
            ok, msg = check_fn()
            results[name] = {"ok": ok, "msg": msg}
            if ok:
                log(f"  ✅ {name}: {msg}")
            else:
                log(f"  ❌ {name}: {msg}")
                all_ok = False
        except Exception as e:
            results[name] = {"ok": False, "msg": str(e)}
            log(f"  ❌ {name}: 异常 {e}")
            all_ok = False
    
    # 保存结果
    result_data = {
        "timestamp": datetime.now().isoformat(),
        "all_ok": all_ok,
        "results": results,
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    
    log(f"巡检完成: {'✅ 全部正常' if all_ok else '❌ 存在异常'}")
    
    if not all_ok:
        # 推送告警
        alert_msg = f"⚠️ 运维巡检异常 ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
        for name, r in results.items():
            if not r["ok"]:
                alert_msg += f"  ❌ {name}: {r['msg']}\n"
        push_alert(alert_msg)
        log("已推送异常告警到企微")
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
