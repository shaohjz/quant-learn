"""
swing_auto.py — 短线波段自动扫描脚本
纯脚本，不依赖LLM，定时执行后推送到企微webhook

功能：
1. 扫描稳定型股票池
2. 技术分析（均线、量能、RSI、布林带）
3. 计算盈亏比（含手续费）
4. 筛选1-5天短线波段机会
5. 推送结果到企微webhook
"""

import os
import sys
import json
import time
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from wecom_webhook import push_markdown
from quant_core.swing_params import load_swing_params
from sim.config_resolver import resolve_artifact_root, resolve_db_path

DB_PATH = resolve_db_path()

# 信号阈值/筛选/执行参数的唯一真源见 quant_core/swing_params.py。
# 默认值与迁移前的硬编码常量逐个相同，由 tests/test_swing_params.py 钉住。
# review/spec.py 会比对本模块与 swing_daily_report / swing_intraday_watch 的取值，
# 迁移不完整（那两处仍用本地常量）时报 partial_migration。
PARAMS = load_swing_params()

# ========== 交易费用 ==========
COMMISSION_RATE = 0.00025   # 佣金万2.5
MIN_COMMISSION = 5.0        # 最低佣金5元
STAMP_TAX_RATE = 0.0005     # 印花税万5（卖出，2023-08-28后）

# ========== 种子池（动态池缺失时兜底；日常以 output/swing_pool/latest.json 为准） ==========
STOCK_POOL = [
    # 银行
    ("sh600036", "招商银行"), ("sh601166", "兴业银行"), ("sh600000", "浦发银行"),
    ("sh601398", "工商银行"), ("sh601939", "建设银行"), ("sh601288", "农业银行"),
    ("sh601328", "交通银行"), ("sh601009", "南京银行"),
    # 保险
    ("sh601318", "中国平安"), ("sh601628", "中国人寿"), ("sh601601", "中国太保"),
    # 消费
    ("sh600519", "贵州茅台"), ("sh600887", "伊利股份"), ("sh600809", "山西汾酒"),
    ("sz000568", "泸州老窖"), ("sz000858", "五粮液"),
    # 电力
    ("sh600900", "长江电力"), ("sh600886", "国投电力"), ("sh600025", "华能水电"),
    ("sh601985", "中国核电"), ("sh600011", "华能国际"),
    # 家电
    ("sz000333", "美的集团"), ("sz000651", "格力电器"), ("sh600690", "海尔智家"),
    # 煤炭
    ("sh601088", "中国神华"), ("sh600188", "兖矿能源"),
    # 运营商
    ("sh600941", "中国移动"), ("sh600050", "中国联通"),
    # 基建
    ("sh601390", "中国中铁"), ("sh601668", "中国建筑"), ("sh601800", "中国交建"),
    # 石化
    ("sh600028", "中国石化"), ("sh601857", "中国石油"),
    # 医药
    ("sh600276", "恒瑞医药"), ("sz000538", "云南白药"),
    # 汽车
    ("sh600104", "上汽集团"),
    # 宽基ETF
    ("sh510050", "上证50ETF"), ("sh510300", "沪深300ETF"),
    ("sh510500", "中证500ETF"), ("sh510880", "红利ETF"),
    # 券商
    ("sh600030", "中信证券"), ("sh601211", "国泰君安"),
    # 建材
    ("sh600585", "海螺水泥"), ("sh600019", "宝钢股份"),
]

def _swing_pool_latest() -> Path:
    return resolve_artifact_root() / "swing_pool" / "latest.json"


def get_stock_pool(allow_stale: bool = True) -> list[tuple[str, str]]:
    """读每日动态稳定池；缺失/损坏则回退 STOCK_POOL。

    allow_stale=True：日期不是今天也用（盘中别因 builder 挂了就空扫）。
    """
    latest = _swing_pool_latest()
    if not latest.exists():
        return list(STOCK_POOL)
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return list(STOCK_POOL)
    if not allow_stale and data.get("date") != date.today().isoformat():
        return list(STOCK_POOL)
    stocks = data.get("stocks") or []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for s in stocks:
        code = str(s.get("prefixed") or s.get("code") or "")
        if not code:
            continue
        if code.isdigit() or (len(code) == 6 and not code.startswith(("sh", "sz"))):
            c6 = code.zfill(6)[-6:]
            code = ("sh" if c6.startswith(("5", "6", "9")) else "sz") + c6
        name = str(s.get("name") or code)
        if code in seen:
            continue
        seen.add(code)
        out.append((code, name))
    return out if out else list(STOCK_POOL)


def get_quote(code):
    """获取腾讯行情"""
    url = f'https://qt.gtimg.cn/q={code}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        vals = data.split('"')[1].split('~')
        return {
            'name': vals[1], 'code': vals[2],
            'price': float(vals[3]) if vals[3] else 0,
            'prev_close': float(vals[4]) if vals[4] else 0,
            'change_pct': float(vals[32]) if vals[32] else 0,
            'volume': int(vals[6]) if vals[6] else 0,
            'amount': float(vals[37]) if vals[37] else 0,
            'turnover_rate': float(vals[38]) if vals[38] else 0,
            'pe_ttm': float(vals[39]) if vals[39] else 0,
            'pb': float(vals[46]) if vals[46] else 0,
        }
    except:
        return None


def get_kline(code, days=30):
    """获取日K线"""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        key = code
        days_data = data.get('data', {}).get(key, {}).get('day', [])
        if not days_data:
            days_data = data.get('data', {}).get(key, {}).get('qfqday', [])
        klines = []
        for d in days_data:
            klines.append({
                'date': d[0], 'open': float(d[1]), 'close': float(d[2]),
                'high': float(d[3]), 'low': float(d[4]), 'volume': float(d[5]),
            })
        return klines
    except:
        return None


def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calc_rsi(prices, period=6):
    if len(prices) < period + 1:
        return 50
    gains, losses = 0, 0
    for i in range(-period, 0):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))


def calc_bollinger(prices, period=20):
    """计算布林带"""
    if len(prices) < period:
        return None, None, None
    ma = sum(prices[-period:]) / period
    variance = sum((p - ma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    return ma, ma - 2 * std, ma + 2 * std


def calc_fees(buy_price, sell_price, shares):
    """计算买卖总手续费"""
    buy_comm = max(buy_price * shares * COMMISSION_RATE, MIN_COMMISSION)
    sell_comm = max(sell_price * shares * COMMISSION_RATE, MIN_COMMISSION)
    stamp_tax = sell_price * shares * STAMP_TAX_RATE
    return buy_comm + sell_comm + stamp_tax


def scan_stock(code, name):
    """扫描单只股票，返回波段机会（含盈亏比）"""
    quote = get_quote(code)
    if not quote or quote['price'] == 0:
        return None
    
    klines = get_kline(code, 30)
    if not klines or len(klines) < 20:
        return None
    
    closes = [k['close'] for k in klines]
    volumes = [k['volume'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    
    price = quote['price']
    change_pct = quote['change_pct']
    pe_ttm = quote['pe_ttm']
    
    # 均线
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None
    if not all([ma5, ma10, ma20]):
        return None
    
    # RSI
    rsi = calc_rsi(closes, 6)
    
    # 布林带
    boll_mid, boll_lower, boll_upper = calc_bollinger(closes, 20)
    
    # 量比
    avg_vol_5 = sum(volumes[-5:]) / 5
    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
    today_vol_ratio = volumes[-1] / avg_vol_5 if avg_vol_5 > 0 else 1
    
    # 近5日平均振幅
    amps = []
    for i in range(-5, 0):
        amp = (highs[i] - lows[i]) / closes[i-1] * 100
        amps.append(amp)
    avg_amp = sum(amps) / len(amps) if amps else 0
    
    # 近5日最大涨跌幅
    max_up_5 = max(((closes[i] - closes[i-1]) / closes[i-1] * 100) for i in range(-5, 0))
    max_down_5 = min(((closes[i] - closes[i-1]) / closes[i-1] * 100) for i in range(-5, 0))
    
    # === 信号判断 ===
    signals = []
    signal_type = None
    
    # 信号1: 缩量回踩MA20支撑（最可靠）
    a_tol = PARAMS.a_ma20_tolerance
    if price <= ma20 * (1 + a_tol) and price >= ma20 * (1 - a_tol):
        if today_vol_ratio < PARAMS.max_volume_ratio:
            signals.append(("缩量回踩MA20", 4))
            signal_type = 'A'
    
    # 信号2: 缩量回踩MA10支撑
    b_tol = PARAMS.b_ma10_tolerance
    if price <= ma10 * (1 + b_tol) and price >= ma10 * (1 - b_tol):
        if today_vol_ratio < PARAMS.max_volume_ratio:
            signals.append(("缩量回踩MA10", 3))
            if not signal_type:
                signal_type = 'B'
    
    # 信号3: 布林下轨附近
    if boll_lower and price <= boll_lower * (1 + PARAMS.boll_lower_tolerance):
        signals.append(("布林下轨附近", 3))
        if not signal_type:
            signal_type = 'C'
    
    # 信号4: RSI超卖
    if rsi < PARAMS.rsi_oversold:
        signals.append((f"RSI超卖({rsi:.0f})", 3))
        if not signal_type:
            signal_type = 'D'
    
    # 信号5: 连续下跌后缩量企稳
    if len(closes) >= 5:
        last_3 = closes[-3:]
        if all(last_3[i] < last_3[i-1] for i in range(1, 3)):
            if today_vol_ratio < PARAMS.quiet_volume_ratio and change_pct >= PARAMS.e_min_change_pct:
                signals.append(("三连阴缩量企稳", 4))
                if not signal_type:
                    signal_type = 'E'
    
    # 信号6: 回调缩量（单日大跌缩量）
    if change_pct < PARAMS.f_max_change_pct and today_vol_ratio < PARAMS.quiet_volume_ratio:
        signals.append((f"大跌缩量({change_pct:.1f}%)", 2))
        if not signal_type:
            signal_type = 'F'
    
    if not signals:
        return None
    
    # === 计算盈亏比 ===
    score = sum(s[1] for s in signals)
    
    # 支撑位：ma20 > ma10 > 近期低点
    support_candidates = []
    if ma20: support_candidates.append(('MA20', ma20))
    if ma10: support_candidates.append(('MA10', ma10))
    if ma60: support_candidates.append(('MA60', ma60))
    recent_low_5 = min(lows[-5:])
    support_candidates.append(('5日低点', recent_low_5))
    
    # 选低于当前价且最接近的支撑
    valid_supports = [(n, v) for n, v in support_candidates if v < price]
    if valid_supports:
        support_name, support = max(valid_supports, key=lambda x: x[1])
    else:
        support_name, support = '5日低点', recent_low_5
    
    # 阻力位：ma5 > ma10 > 近期高点
    resist_candidates = []
    if ma5: resist_candidates.append(('MA5', ma5))
    if ma10: resist_candidates.append(('MA10', ma10))
    if ma20: resist_candidates.append(('MA20', ma20))
    recent_high_5 = max(highs[-5:])
    resist_candidates.append(('5日高点', recent_high_5))
    
    valid_resists = [(n, v) for n, v in resist_candidates if v > price]
    if valid_resists:
        resist_name, resist = min(valid_resists, key=lambda x: x[1])
    else:
        resist_name, resist = '5日高点', recent_high_5
    
    # 盈亏比
    upside = (resist - price) / price
    downside = (price - support) / price if support < price else 0.01
    
    if downside <= 0:
        return None
    
    risk_reward = upside / downside
    
    # 计算手续费影响（按100股计算）
    test_shares = 100
    fees = calc_fees(price, resist, test_shares)
    fee_ratio = fees / (price * test_shares)
    
    net_upside = upside - fee_ratio
    net_downside = downside + fee_ratio
    net_rr = net_upside / net_downside if net_downside > 0 else 0
    
    # 最终筛选
    if net_rr < PARAMS.min_net_rr:
        return None
    if upside < PARAMS.min_upside_pct:
        return None
    if avg_amp < PARAMS.min_avg_amp:
        return None
    
    # 建议仓位
    suggested_shares = max(100, int(10000 / price / 100) * 100)  # 约1万元
    
    return {
        'name': name, 'code': code,
        'price': round(price, 2),
        'change_pct': round(change_pct, 2),
        'pe_ttm': pe_ttm,
        'ma5': round(ma5, 2), 'ma10': round(ma10, 2), 'ma20': round(ma20, 2),
        'rsi': round(rsi, 1),
        'avg_amp': round(avg_amp, 1),
        'vol_ratio': round(vol_ratio, 2),
        'today_vol_ratio': round(today_vol_ratio, 2),
        'signals': signals,
        'signal_type': signal_type,
        'score': score,
        'support_name': support_name,
        'support': round(support, 2),
        'resist_name': resist_name,
        'resist': round(resist, 2),
        'upside_pct': round(upside * 100, 2),
        'downside_pct': round(downside * 100, 2),
        'risk_reward': round(risk_reward, 2),
        'net_rr': round(net_rr, 2),
        'fee_ratio': round(fee_ratio * 100, 3),
        'suggested_shares': suggested_shares,
        'suggested_amount': round(suggested_shares * price, 2),
    }


SWING_ACCOUNT_ID = 3


def get_account_info(account_id: int = SWING_ACCOUNT_ID):
    """获取波段模拟账户信息（默认 #3）。"""
    db = sqlite3.connect(str(DB_PATH))
    c = db.cursor()
    # 兼容旧表名 sim_account / 新表 sim_accounts
    row = None
    for sql in (
        "SELECT total_value, cash FROM sim_accounts WHERE id = ?",
        "SELECT total_value, cash FROM sim_account WHERE id = ?",
    ):
        try:
            c.execute(sql, (account_id,))
            row = c.fetchone()
            if row:
                break
        except sqlite3.OperationalError:
            continue
    c.execute(
        "SELECT cumulative_return FROM sim_daily_nav WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,),
    )
    nav = c.fetchone()
    c.execute(
        "SELECT stock_name, stock_code, quantity, avg_cost, current_price, pnl_pct "
        "FROM sim_positions WHERE account_id = ? AND quantity > 0",
        (account_id,),
    )
    positions = [
        {'name': r[0], 'code': r[1], 'qty': r[2], 'cost': r[3], 'price': r[4], 'pnl_pct': r[5]}
        for r in c.fetchall()
    ]
    db.close()
    return {
        'total': row[0] if row else 0,
        'cash': row[1] if row else 0,
        'total_pnl_pct': (nav[0] * 100) if nav and nav[0] is not None else 0,
        'positions': positions,
        'account_id': account_id,
    }


def save_results(results, scan_date):
    """保存到数据库"""
    db = sqlite3.connect(str(DB_PATH))
    c = db.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS swing_scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT, stock_code TEXT, stock_name TEXT,
            price REAL, change_pct REAL, score INTEGER,
            signals TEXT, signal_type TEXT,
            support REAL, resist REAL,
            upside_pct REAL, downside_pct REAL,
            risk_reward REAL, net_rr REAL, fee_ratio REAL,
            pe_ttm REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for r in results:
        c.execute("""
            INSERT INTO swing_scan_results 
            (scan_date, stock_code, stock_name, price, change_pct, score, signals, signal_type,
             support, resist, upside_pct, downside_pct, risk_reward, net_rr, fee_ratio, pe_ttm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scan_date, r['code'], r['name'], r['price'], r['change_pct'],
            r['score'], "; ".join(s[0] for s in r['signals']), r['signal_type'],
            r['support'], r['resist'],
            r['upside_pct'], r['downside_pct'],
            r['risk_reward'], r['net_rr'], r['fee_ratio'], r['pe_ttm']
        ))
    db.commit()
    db.close()


def build_report(results, account, title: str | None = None):
    """生成企微Markdown报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    lines = []
    lines.append(f"# {title or '盘前波段扫描报告'}")
    pool = get_stock_pool()
    aid = account.get("account_id", SWING_ACCOUNT_ID)
    lines.append(f"> 扫描时间：{now} | 扫描范围：{len(pool)}只动态稳定池 | 账户 #{aid}")
    lines.append("")
    
    # 账户概况
    lines.append("## 账户概况")
    lines.append(f"> 总资产：**{account['total']:.2f}** | 现金：**{account['cash']:.2f}**")
    lines.append(f"> 累计收益：**{account['total_pnl_pct']:+.2f}%** | 持仓：**{len(account['positions'])}**只")
    lines.append("")
    
    if not results:
        lines.append("## ❌ 今日无信号")
        lines.append("当前动态稳定池中未发现符合条件的短线波段机会。")
        lines.append("")
        lines.append("**可能原因：**")
        lines.append("- 市场整体趋势偏强，回调机会较少")
        lines.append("- 池内股票波动偏低或未触发 A/B 信号阈值")
        lines.append("- 建议收盘后再次扫描确认")
        return "\n".join(lines)
    
    # 按评分分组
    high = [r for r in results if r['score'] >= 5]
    watch = [r for r in results if 3 <= r['score'] < 5]
    
    lines.append(f"## 🎯 发现 {len(results)} 只短线机会")
    lines.append("")
    
    if high:
        lines.append("### 🟢 重点关注（评分≥5）")
        lines.append("| 股票 | 现价 | 涨跌 | 信号 | 支撑→阻力 | 盈亏比 |")
        lines.append("|------|------|------|------|-----------|--------|")
        for r in high:
            sig_short = "; ".join(s[0] for s in r['signals'][:2])
            lines.append(f"| **{r['name']}**({r['code'][-6:]}) | {r['price']:.2f} | {r['change_pct']:+.2f}% | {sig_short} | {r['support_name']}{r['support']:.2f}→{r['resist_name']}{r['resist']:.2f} | **{r['net_rr']:.2f}** |")
        lines.append("")
    
    if watch:
        lines.append("### 🟡 观察列表（评分3-4）")
        lines.append("| 股票 | 现价 | 涨跌 | 信号 | 盈亏比 |")
        lines.append("|------|------|------|------|--------|")
        for r in watch:
            sig_short = "; ".join(s[0] for s in r['signals'][:1])
            lines.append(f"| {r['name']}({r['code'][-6:]}) | {r['price']:.2f} | {r['change_pct']:+.2f}% | {sig_short} | {r['net_rr']:.2f} |")
        lines.append("")
    
    # 详细机会
    lines.append("## 📝 详细分析")
    lines.append("")
    for i, r in enumerate(results[:5]):
        sigs = "、".join(s[0] for s in r['signals'])
        lines.append(f"**{i+1}. {r['name']}({r['code'][-6:]})** — 现价**{r['price']:.2f}** ({r['change_pct']:+.2f}%)")
        lines.append(f"> 信号：{sigs}")
        lines.append(f"> 技术位：支撑**{r['support_name']}{r['support']:.2f}** → 阻力**{r['resist_name']}{r['resist']:.2f}**")
        lines.append(f"> 预期空间：{r['upside_pct']:+.2f}% / {r['downside_pct']:.2f}% | 盈亏比：**{r['risk_reward']:.2f}**(净{r['net_rr']:.2f})")
        lines.append(f"> 手续费：约{r['fee_ratio']:.3f}% | 日均振幅：{r['avg_amp']:.1f}%")
        lines.append(f"> 建议仓位：约{r['suggested_amount']:.0f}元（{r['suggested_shares']}股）")
        lines.append("")
    
    # 操作建议
    lines.append("## 💡 操作建议")
    lines.append("")
    if high:
        lines.append("**买入策略：**")
        for r in high[:3]:
            buy_range = f"{r['support']:.2f}~{r['price']:.2f}"
            target = f"{r['resist']:.2f}"
            stop = f"{r['support'] * 0.98:.2f}"
            lines.append(f"- **{r['name']}**：回踩{buy_range}区间介入，目标{target}，止损{stop}")
        lines.append("")
    
    lines.append("**风控原则：**")
    lines.append("- 单只仓位不超过总资金8%")
    lines.append("- 同时持有波段仓位不超过3只")
    lines.append("- 持有周期1-5天，到阻力位分批止盈")
    lines.append("- 跌破止损价立即离场，不扛单")
    lines.append("")
    lines.append("---")
    lines.append(f"*⚡ 自动扫描脚本 | 数据来源：腾讯行情 | 仅供参考，不构成投资建议*")
    
    return "\n".join(lines)


def main(argv: list[str] | None = None):
    import argparse
    ap = argparse.ArgumentParser(description="盘前/盘中短线波段扫描 → 企微")
    ap.add_argument("--no-push", action="store_true", help="只打印不推企微")
    ap.add_argument(
        "--title",
        default="盘前波段扫描报告",
        help="报告标题（早盘默认盘前）",
    )
    args = ap.parse_args(argv)

    scan_date = date.today().strftime("%Y-%m-%d")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    pool = get_stock_pool()
    print(f"短线波段扫描 - {scan_time}")
    print(f"   股票池: {len(pool)}只（动态稳定池）")

    account = get_account_info()
    print(f"   账户#{account.get('account_id')}: 总资产{account['total']:.2f} 现金{account['cash']:.2f}")

    results = []
    for code, name in pool:
        try:
            r = scan_stock(code, name)
            if r:
                results.append(r)
            time.sleep(0.2)
        except Exception:
            pass

    results.sort(key=lambda x: x['score'], reverse=True)
    print(f"   发现 {len(results)} 只波段机会")

    save_results(results, scan_date)
    print("   结果已保存到数据库")

    report = build_report(results, account, title=args.title)
    if args.no_push:
        print(report)
        print("   推送: 跳过 (--no-push)")
        return results

    ok = push_markdown(report)
    print(f"   推送结果: {'成功' if ok else '失败'}")
    return results


if __name__ == "__main__":
    main()
