"""周一开跑前体检 - 5/24 深夜版"""
import warnings, sys, os, traceback
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
        results.append((name, False, f"EXCEPTION: {type(e).__name__}: {e}"))
        print(f"❌ {name}: EXCEPTION: {type(e).__name__}: {e}")

# 1. sina realtime
def t_sina():
    from sim.realtime_price import fetch_sina_realtime
    r = fetch_sina_realtime(["000967", "002256", "600519"])
    if r and any(d["price"] > 0 for d in r.values()):
        sample = list(r.values())[0]
        return True, f"OK {len(r)} 只，样本: {sample['name']} {sample['price']:.2f}"
    return False, f"无返回或全 0: {r}"

# 2. baostock
def t_bs():
    import baostock as bs
    lg = bs.login()
    ok = lg.error_code == "0"
    bs.logout()
    return ok, f"login={lg.error_code} {lg.error_msg}"

# 3. akshare
def t_ak():
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol="600519", period="daily",
                            start_date="20260520", end_date="20260523", adjust="qfq")
    return (df is not None and not df.empty), f"shape={df.shape if df is not None else None}"

# 4. AKShare 实时（spot_em）
def t_ak_spot():
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    return (df is not None and not df.empty), f"shape={df.shape if df is not None else None}"

# 5. xtquant 数据
def t_xtdata():
    try:
        from xtquant import xtdata
        # 试拉一只票最近 1 天
        codes = ["600519.SH"]
        xtdata.subscribe_quote(codes[0], period="1d")
        kdata = xtdata.get_market_data_ex(
            field_list=["close", "volume"],
            stock_list=codes,
            period="1d",
            start_time="20260520",
            end_time="20260523",
        )
        df = kdata.get(codes[0])
        if df is not None and not df.empty:
            return True, f"OK shape={df.shape} last_close={df['close'].iloc[-1]}"
        return False, f"empty result: {kdata}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

# 6. xtquant 交易（连接到 mini 客户端）
def t_qmt_trade():
    try:
        from xtquant import xttrader
        # 不真连，只检查模块加载
        return True, "xttrader 模块可加载"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

# 7. config 加载
def t_config():
    from sim.config import load_config
    c = load_config()
    accounts = c.get("accounts", [])
    return len(accounts) > 0, f"accounts={[a.get('id') for a in accounts]}"

# 8. portfolio_alert 干跑
def t_alert_dry():
    import subprocess
    p = subprocess.run([".venv\\Scripts\\python.exe", "-u", "scripts\\portfolio_alert.py"],
                       capture_output=True, text=True, timeout=60, cwd=".",
                       env={**os.environ, "NOTIFIER_DRY_RUN": "1"})
    last_lines = (p.stdout + p.stderr).strip().split("\n")[-3:]
    return p.returncode == 0, f"rc={p.returncode}, tail: {last_lines}"

# 9. morning_brief 干跑（这是 9:25 那个）
def t_morning_brief_dry():
    import subprocess
    p = subprocess.run([".venv\\Scripts\\python.exe", "-u", "scripts\\morning_brief.py"],
                       capture_output=True, text=True, timeout=120, cwd=".")
    last_lines = (p.stdout + p.stderr).strip().split("\n")[-5:]
    return p.returncode == 0, f"rc={p.returncode}, tail: {last_lines}"

# 10. morning_scanner 干跑
def t_scanner_dry():
    import subprocess
    p = subprocess.run([".venv\\Scripts\\python.exe", "-u", "scripts\\morning_scanner.py", "--dry-run"],
                       capture_output=True, text=True, timeout=180, cwd=".")
    last_lines = (p.stdout + p.stderr).strip().split("\n")[-5:]
    return p.returncode == 0, f"rc={p.returncode}, tail: {last_lines}"

print("=" * 80)
print(" 周一开跑前体检 - 数据源 / 模块 / 关键脚本")
print("=" * 80)

check("1. 新浪实时行情 (盘中价格主源)", t_sina)
check("2. baostock (历史日线主源)", t_bs)
check("3. akshare 历史 stock_zh_a_hist", t_ak)
check("4. akshare 实时 stock_zh_a_spot_em", t_ak_spot)
check("5. xtquant.xtdata 历史数据", t_xtdata)
check("6. xtquant.xttrader 模块", t_qmt_trade)
check("7. sim.config 加载", t_config)
check("8. portfolio_alert.py 干跑", t_alert_dry)
check("9. morning_brief.py 干跑", t_morning_brief_dry)
check("10. morning_scanner.py 干跑", t_scanner_dry)

print("\n" + "=" * 80)
print(" 体检汇总")
print("=" * 80)
ok = sum(1 for _, o, _ in results if o)
print(f" 通过: {ok}/{len(results)}")
for name, o, msg in results:
    s = "✅" if o else "❌"
    print(f"  {s} {name}")
