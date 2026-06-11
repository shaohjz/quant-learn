"""开盘前体检 v2 - 验证修复后状态"""
import warnings, sys, os, subprocess
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')

results = []

def check(name, fn):
    try:
        ok, msg = fn()
        status = "✅" if ok else "❌"
        results.append((name, ok, msg))
        print(f"{status} {name}: {msg}")
    except Exception as e:
        results.append((name, False, f"EXC: {type(e).__name__}: {e}"))
        print(f"❌ {name}: EXC: {type(e).__name__}: {e}")

# 数据源
def t_sina():
    from sim.realtime_price import fetch_sina_realtime
    r = fetch_sina_realtime(["000967", "002256", "600519"])
    if r and any(d["price"] > 0 for d in r.values()):
        s = list(r.values())[0]
        return True, f"OK {len(r)} 只，{s['name']} {s['price']:.2f}"
    return False, "无返回"

def t_bs():
    import baostock as bs
    lg = bs.login(); ok = lg.error_code == "0"; bs.logout()
    return ok, f"login={lg.error_code}"

def t_ak():
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol="600519", period="daily",
                            start_date="20260520", end_date="20260523", adjust="qfq")
    return (df is not None and not df.empty), f"shape={df.shape if df is not None else None}"

# 关键脚本
def run_script(args, timeout=120, env_extra=None):
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([".venv\\Scripts\\python.exe", "-u"] + args,
                       capture_output=True, text=True, timeout=timeout, cwd=".", env=env,
                       encoding="utf-8", errors="replace")
    tail = (p.stdout + p.stderr).strip().split("\n")[-3:]
    return p.returncode == 0, f"rc={p.returncode}, tail={tail}"

def t_morning_brief():
    return run_script(["scripts/morning_brief.py"], timeout=120)

def t_scanner_lite():
    return run_script(["scripts/scanner_lite.py", "--no-webhook", "--top", "5"], timeout=60)

def t_scanner_fallback():
    """这个在凌晨跑，主路径会超时（120s），然后切 lite。"""
    return run_script(["scripts/scanner_with_fallback.py"], timeout=180)

def t_portfolio_alert_dry():
    return run_script(["scripts/portfolio_alert.py"], timeout=60,
                      env_extra={"NOTIFIER_DRY_RUN": "1"})

def t_intraday_auction():
    return run_script(["scripts/intraday_watch.py", "auction"], timeout=60)

def t_qmt_xtdata():
    p = subprocess.run([".venv\\Scripts\\python.exe", "scripts/test_xtdata.py"],
                       capture_output=True, text=True, timeout=30, cwd=".",
                       encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).strip()
    if "无法连接行情服务" in out:
        return False, "QMT mini 客户端未运行（需手动启动）"
    return p.returncode == 0, f"out={out[-100:]}"

print("=" * 80)
print(" 体检 v2 - 修复后验证 (2026-05-25 凌晨)")
print("=" * 80)

print("\n[数据源]")
check("Sina realtime（盘中主源）", t_sina)
check("Baostock（历史日线主源）", t_bs)
check("AKShare（云桌面已断）", t_ak)

print("\n[关键脚本]")
check("morning_brief 9:25 OpenClaw cron", t_morning_brief)
check("scanner_lite 降级版", t_scanner_lite)
check("scanner_with_fallback (cron 入口)", t_scanner_fallback)
check("portfolio_alert dry-run", t_portfolio_alert_dry)
check("intraday_watch auction", t_intraday_auction)

print("\n[QMT]")
check("xtdata 行情连接", t_qmt_xtdata)

print("\n" + "=" * 80)
ok = sum(1 for _, o, _ in results if o)
print(f" 通过 {ok}/{len(results)}")
print("=" * 80)

# 把结果写到 STATUS.md
status_md = "STATUS_2026-05-25.md"
with open(status_md, "w", encoding="utf-8") as f:
    f.write("# 周一开盘前体检报告 - 2026-05-25 凌晨\n\n")
    f.write("## 通过统计\n\n")
    f.write(f"**{ok} / {len(results)}** 项通过\n\n")
    f.write("## 详细\n\n| 项目 | 状态 | 说明 |\n|---|:-:|---|\n")
    for name, o, msg in results:
        s = "✅" if o else "❌"
        f.write(f"| {name} | {s} | `{msg[:80]}` |\n")
    f.write("\n_体检脚本：scripts/_healthcheck_v2_2026-05-25.py_\n")
print(f"\n📋 STATUS 写入 {status_md}")
