#!/usr/bin/env python
"""
scripts/intraday_scanner.py — 盘中异动扫描（自动观察池管理）

功能：
  - 盘中每 30 分钟扫描沪深300 + 中证500（约 800 只）
  - 识别异动信号：量价突破 / 涨停回落 / 超跌反弹
  - 自动加入 config.yaml (watchlist.auto_discovered)
  - 推送企微通知
  - 记录到 watchlist_history 表

异动信号定义：
  1. 量价突破 (score 80-95): 价格 > MA20 + 量比 ≥ 1.5 + 涨幅 1-5% + 接近20日高
  2. 涨停回落 (score 70-80): 早盘涨停 + 当前回落至 5-8% + 量能持续
  3. 超跌反弹 (score 60-75): 近5日跌 > 10% + 今日放量反弹 3-6% + 未破 MA60

使用：
  python scripts/intraday_scanner.py [--top 5] [--no-webhook] [--dry-run]

计划任务：
  每 30 分钟运行一次（9:30/10:00/.../14:30），仅交易时段
"""
import sys
import json
import logging
import argparse
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime, date, time as dtime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT / "output" / "intraday_scans"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = ROOT / "data" / "sim_live_mirror.db"
CONFIG_FILE = ROOT / "config.yaml"
CONFIG_AUTO_FILE = ROOT / "config_auto.yaml"

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

# 跨平台文件锁
import os
if os.name == 'nt':
    import msvcrt
    def lock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    def unlock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl
    def lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    def unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def save_config(cfg):
    """保存配置（带文件锁，避免并发写冲突）"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        lock_file(f)  # 加锁
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        unlock_file(f)  # 解锁

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
#  交易时段检查
# ====================================================================
def in_trade_hours(now: datetime = None) -> bool:
    """A股交易时段：周一到周五 9:30-11:30 / 13:00-15:00"""
    if now is None:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))

# ====================================================================
#  股票池
# ====================================================================
UNIVERSE_CACHE = ROOT / "data" / "universe_cache.json"

def get_universe():
    """获取股票池：从本地缓存读取（由 BaoStock 每周生成）"""
    if UNIVERSE_CACHE.exists():
        try:
            data = json.loads(UNIVERSE_CACHE.read_text(encoding='utf-8'))
            codes = data.get('codes', [])
            if len(codes) > 100:
                logger.info(f"股票池(缓存): {len(codes)} 只")
                return codes
        except Exception:
            pass
    
    # 缓存不存在时尝试 BaoStock 拉取
    try:
        import baostock as bs
        bs.login()
        codes = set()
        rs = bs.query_hs300_stocks()
        while rs.error_code == '0' and rs.next():
            codes.add(rs.get_row_data()[1].replace('sh.','').replace('sz.',''))
        rs = bs.query_zz500_stocks()
        while rs.error_code == '0' and rs.next():
            codes.add(rs.get_row_data()[1].replace('sh.','').replace('sz.',''))
        bs.logout()
        logger.info(f"股票池(BaoStock): {len(codes)} 只")
        # 保存缓存
        UNIVERSE_CACHE.write_text(json.dumps({
            'codes': sorted(codes), 'updated': datetime.now().isoformat(), 'count': len(codes)
        }, ensure_ascii=False), encoding='utf-8')
        return sorted(codes)
    except Exception as e:
        logger.error(f"BaoStock 拉取失败: {e}")
        return []

# ====================================================================
#  实时行情拉取
# ====================================================================
def fetch_all_realtime():
    """拉取全市场实时行情（纯新浪HTTP，不依赖akshare）"""
    import re as _re
    import requests
    import pandas as pd
    
    universe = get_universe()
    if not universe:
        raise RuntimeError("股票池为空")
    
    # 转新浪代码格式
    sina_codes = []
    for code in universe:
        if code.startswith(('60', '68', '11', '5')):
            sina_codes.append('sh' + code)
        else:
            sina_codes.append('sz' + code)
    
    # 批量拉取（每批 80 只）
    all_data = []
    headers = {'Referer': 'https://finance.sina.com.cn'}
    batch_size = 80
    
    for i in range(0, len(sina_codes), batch_size):
        batch = sina_codes[i:i+batch_size]
        url = 'https://hq.sinajs.cn/list=' + ','.join(batch)
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.encoding = 'gbk'
            for line in r.text.strip().split('\n'):
                m = _re.search(r'hq_str_(s[hz])(\d+)="(.+?)"', line)
                if not m:
                    continue
                code = m.group(2)
                parts = m.group(3).split(',')
                if len(parts) < 10 or not parts[3]:
                    continue
                try:
                    price = float(parts[3])
                    yclose = float(parts[2])
                    high = float(parts[4])
                    low = float(parts[5])
                    volume = float(parts[8])
                    amount = float(parts[9])
                except (ValueError, IndexError):
                    continue
                if price <= 0 or yclose <= 0:
                    continue
                all_data.append({
                    '代码': code,
                    '名称': parts[0],
                    '最新价': price,
                    '昨收': yclose,
                    '最高': high,
                    '最低': low,
                    '涨跌幅': (price - yclose) / yclose * 100,
                    '成交量': volume,
                    '成交额': amount,
                })
        except Exception as e:
            logger.warning(f"新浪批次 {i//batch_size} 失败: {e}")
            time.sleep(0.3)
    
    if not all_data:
        raise RuntimeError("新浪实时行情拉取失败")
    
    df = pd.DataFrame(all_data)
    logger.info(f"实时行情(新浪): {len(df)} 条")
    return df

def get_kline(code: str, days: int = 30, retries: int = 3):
    """拉单只 K 线（带重试）"""
    import akshare as ak
    last_err = None
    for attempt in range(retries):
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq",
                                    start_date=(datetime.now() - __import__("datetime").timedelta(days=days*2)).strftime("%Y%m%d"))
            if df is None or len(df) == 0:
                return None
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
    logger.debug(f"{code} 拉K线失败: {last_err}")
    return None

# ====================================================================
#  风险过滤
# ====================================================================
def filter_universe(codes, spot_df):
    """对股票池做风险过滤"""
    spot_map = {row["代码"]: row for _, row in spot_df.iterrows()}
    
    filtered = []
    for code in codes:
        row = spot_map.get(code)
        if row is None:
            continue
        name = str(row.get("名称", ""))
        if "ST" in name:
            continue
        try:
            price = float(row.get("最新价", 0))
            pct = float(row.get("涨跌幅", 0))
            amount = float(row.get("成交额", 0))
        except Exception:
            continue
        
        if price <= 2 or price > 500:  # 价格范围
            continue
        if abs(pct) > 7:  # 避免追高/恐慌盘
            continue
        if amount < 1e8:  # 流动性过滤
            continue
        
        filtered.append({"code": code, "name": name, "price": price, "pct": pct, "amount": amount})
    
    return filtered

# ====================================================================
#  异动信号识别
# ====================================================================
def calc_anomaly_score(code: str, hist_df, spot_row):
    """
    计算异动评分 (0-100)
    
    返回: {
        'code': code,
        'name': name,
        'price': float,
        'pct_chg': float,
        'signal_type': 'volume_breakout' | 'pullback_from_limit' | 'oversold_bounce',
        'score': float (0-100),
        'reason': str,
        'factors': {...}
    }
    """
    if hist_df is None or len(hist_df) < 60:
        return None
    
    c = hist_df["收盘"].astype(float)
    v = hist_df["成交量"].astype(float)
    h = hist_df["最高"].astype(float)
    
    if len(c) < 20:
        return None
    
    last = float(c.iloc[-1])
    ma5 = c.tail(5).mean()
    ma10 = c.tail(10).mean()
    ma20 = c.tail(20).mean()
    ma60 = c.tail(60).mean() if len(c) >= 60 else ma20
    avg_vol5 = v.tail(5).mean()
    today_vol = float(v.iloc[-1])
    high20 = h.tail(20).max()
    high5 = h.tail(5).max()
    low5 = c.tail(5).min()
    
    pct_chg = spot_row["pct"]
    vol_ratio = today_vol / avg_vol5 if avg_vol5 > 0 else 0
    
    # === 信号1: 量价突破 ===
    if (last > ma20 and 
        vol_ratio >= 1.5 and 
        1 <= pct_chg <= 5 and 
        high5 >= high20 * 0.97):
        
        score = 80
        if vol_ratio >= 2.0:
            score += 5
        if last > ma5 and ma5 > ma10:
            score += 5
        if high5 >= high20:
            score += 5
        
        return {
            'code': code,
            'name': spot_row['name'],
            'price': last,
            'pct_chg': pct_chg,
            'signal_type': 'volume_breakout',
            'score': min(score, 95),
            'reason': f"量价突破（量比{vol_ratio:.1f}，接近20日高）",
            'factors': {
                'vol_ratio': vol_ratio,
                'ma20_dist': (last / ma20 - 1) * 100,
                'high20_dist': (high5 / high20 - 1) * 100,
            }
        }
    
    # === 信号2: 涨停回落 ===
    if pct_chg >= 5 and pct_chg <= 8 and high5 >= last * 1.09:
        # 早盘涨停（最高 >= 当前价 * 1.09），现回落至 5-8%
        if vol_ratio >= 1.5:
            score = 70
            if 6 <= pct_chg <= 7:  # 回落不深不浅最佳
                score += 5
            if vol_ratio >= 2.0:
                score += 5
            
            return {
                'code': code,
                'name': spot_row['name'],
                'price': last,
                'pct_chg': pct_chg,
                'signal_type': 'pullback_from_limit',
                'score': min(score, 80),
                'reason': f"涨停回落（早盘涨停，现+{pct_chg:.1f}%，量比{vol_ratio:.1f}）",
                'factors': {
                    'vol_ratio': vol_ratio,
                    'high_today': high5,
                    'pullback_pct': (high5 / last - 1) * 100,
                }
            }
    
    # === 信号3: 超跌反弹 ===
    drop5d = (low5 / c.iloc[-6] - 1) * 100 if len(c) >= 6 else 0
    if (drop5d < -10 and  # 近5日跌超 10%
        3 <= pct_chg <= 6 and  # 今日反弹 3-6%
        vol_ratio >= 2.0 and  # 放量
        last > ma60):  # 未破 MA60
        
        score = 60
        if vol_ratio >= 2.5:
            score += 5
        if last > ma20:  # 站上 MA20 加分
            score += 5
        if 4 <= pct_chg <= 5:  # 反弹力度适中
            score += 5
        
        return {
            'code': code,
            'name': spot_row['name'],
            'price': last,
            'pct_chg': pct_chg,
            'signal_type': 'oversold_bounce',
            'score': min(score, 75),
            'reason': f"超跌反弹（近5日跌{abs(drop5d):.1f}%，今日反弹+{pct_chg:.1f}%，量比{vol_ratio:.1f}）",
            'factors': {
                'vol_ratio': vol_ratio,
                'drop5d': drop5d,
                'ma60_dist': (last / ma60 - 1) * 100,
            }
        }
    
    return None  # 无异动信号

# ====================================================================
#  数据库操作
# ====================================================================
def add_to_watchlist_history(code, name, score, reason, signal_type):
    """记录到 watchlist_history 表"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    today = date.today().isoformat()
    
    metadata = json.dumps({
        "signal_type": signal_type,
        "discovery_time": datetime.now().strftime("%H:%M")
    }, ensure_ascii=False)
    
    try:
        c.execute("""
            INSERT OR IGNORE INTO watchlist_history
            (code, name, category, added_at, added_by, added_reason, discovery_score, metadata)
            VALUES (?, ?, 'auto_discovered', ?, 'intraday_scanner', ?, ?, ?)
        """, (code, name, today, reason, score, metadata))
        conn.commit()
    except sqlite3.IntegrityError as e:
        logger.warning(f"插入 watchlist_history 失败: {e}")
    finally:
        conn.close()

def load_config_auto():
    """加载 config_auto.yaml"""
    if not CONFIG_AUTO_FILE.exists():
        return {"auto_discovered": {}, "cooldown": {}}
    with open(CONFIG_AUTO_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"auto_discovered": {}, "cooldown": {}}

def save_config_auto(cfg):
    """保存 config_auto.yaml（带文件锁）"""
    with open(CONFIG_AUTO_FILE, "w", encoding="utf-8") as f:
        lock_file(f)
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        unlock_file(f)

def get_existing_auto_discovered():
    """获取当前 config_auto.yaml 中已存在的 auto_discovered 股票代码"""
    cfg = load_config_auto()
    auto = cfg.get("auto_discovered", {})
    return set(auto.keys())

def check_cooldown(code: str) -> tuple[bool, str]:
    """检查股票是否在冷却期
    
    返回: (is_cooldown, reason)
    """
    cfg = load_config_auto()
    cooldown = cfg.get("cooldown", {})
    if code not in cooldown:
        return False, ""
    
    entry = cooldown[code]
    from datetime import datetime, timedelta
    removed_at = datetime.fromisoformat(entry["removed_at"])
    cooldown_days = entry.get("cooldown_days", 10)
    removed_count = entry.get("removed_count", 1)
    
    # 累计淘汰 >= 3 次 → 永久黑名单
    if removed_count >= 3:
        return True, f"永久黑名单（累计淘汰 {removed_count} 次）"
    
    # 计算冷却期截止日期
    cooldown_until = removed_at + timedelta(days=cooldown_days)
    if datetime.now() < cooldown_until:
        remaining_days = (cooldown_until - datetime.now()).days
        return True, f"冷却期剩余 {remaining_days} 天（第 {removed_count} 次淘汰）"
    
    return False, ""

def add_to_config_watchlist(discoveries, dry_run=False):
    """添加到 config_auto.yaml 的 auto_discovered"""
    if dry_run:
        logger.info("[DRY RUN] 跳过写入 config_auto.yaml")
        return
    
    cfg = load_config_auto()
    auto = cfg.get("auto_discovered", {})
    if "auto_discovered" not in cfg:
        cfg["auto_discovered"] = {}
    
    for d in discoveries:
        code = d['code']
        if code in auto:
            logger.info(f"  {code} 已存在于 auto_discovered，跳过")
            continue
        
        # 计算动态阈值（基于当前价的 MA10/MA20 估算）
        buy_zone = round(d['price'] * 0.97, 2)  # 回踩 3%
        buy_strong = round(d['price'] * 0.93, 2)  # 回踩 7%
        trend_break = round(d['price'] * 0.85, 2)  # 跌破 15%
        
        auto[code] = {
            "name": d['name'],
            "enabled": True,
            "source": "intraday_scanner",
            "added_at": date.today().isoformat(),
            "added_by": "盘中异动扫描",
            "added_reason": d['reason'],
            "discovery_score": d['score'],
            "signal_type": d['signal_type'],
            "last_alert_at": None,
            "alert_count": 0,
            "max_inactive_days": 7,
            "tags": [],
            "rules": {
                "buy_zone": {
                    "trigger": buy_zone,
                    "dir": "below",
                    "msg": f"💰 {d['name']}回踩至 {buy_zone}！试探建仓"
                },
                "buy_strong": {
                    "trigger": buy_strong,
                    "dir": "below",
                    "msg": f"💰💰 {d['name']}跌至 {buy_strong}！优质建仓区"
                },
                "trend_break": {
                    "trigger": trend_break,
                    "dir": "below",
                    "msg": f"⚠️ {d['name']}破 {trend_break}！趋势反转，移除观察"
                }
            }
        }
        logger.info(f"  ✓ 添加 {code} {d['name']} 到 auto_discovered (score={d['score']:.0f})")
    
    cfg["auto_discovered"] = auto
    save_config_auto(cfg)
    logger.info(f"✓ config_auto.yaml 已更新")

# ====================================================================
#  主流程
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="盘中异动扫描")
    parser.add_argument("--top", type=int, default=5, help="最多添加 N 只（防止膨胀）")
    parser.add_argument("--no-webhook", action="store_true", help="不推送企微")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不写入 config.yaml）")
    parser.add_argument("--force", action="store_true", help="强制运行（忽略交易时段检查）")
    args = parser.parse_args()
    
    now = datetime.now()
    logger.info(f"=== 盘中异动扫描 开始 {now.strftime('%Y-%m-%d %H:%M')} ===")
    
    # 交易时段检查
    if not args.force and not in_trade_hours(now):
        msg = f"📴 非交易时段 ({now.strftime('%H:%M %A')})，跳过"
        print(msg)
        logger.info("非交易时段，退出")
        return 0
    
    # Step 1: 获取股票池
    universe = get_universe()
    logger.info(f"股票池: {len(universe)} 只")
    
    # Step 2: 拉全市场实时行情
    logger.info("拉全市场实时行情...")
    spot_df = fetch_all_realtime()
    logger.info(f"实时行情: {len(spot_df)} 条")
    
    # Step 3: 风险过滤
    filtered = filter_universe(universe, spot_df)
    logger.info(f"过滤后剩余: {len(filtered)} 只")
    
    # Step 4: 两阶段异动识别
    #   第一阶段：纯用实时行情粗筛候选（涨幅+量比+成交额）
    #   第二阶段：只对候选拉K线做精确判断
    results = []
    start_t = time.time()
    
    # 第一阶段：粗筛（涨幅 1-7% + 量比高 + 成交额大）
    candidates = []
    for item in filtered:
        pct = item['pct']
        amount = item['amount']
        # 基本条件：涨幅1-7% 且 成交额 > 2亿
        if 1 <= pct <= 7 and amount >= 2e8:
            candidates.append(item)
        # 跌幅反弹：之前大跌今日反弹3-6%
        elif 3 <= pct <= 6 and amount >= 1.5e8:
            candidates.append(item)
    
    # 按成交额降序，取前 40 只
    candidates.sort(key=lambda x: x['amount'], reverse=True)
    candidates = candidates[:40]
    logger.info(f"粗筛候选: {len(candidates)} 只（从 {len(filtered)} 只中）")
    
    # 第二阶段：只对候选拉K线
    def process_one(item):
        code = item["code"]
        try:
            df = get_kline(code, days=60)
            if df is None:
                return None
            anomaly = calc_anomaly_score(code, df, item)
            return anomaly
        except Exception as e:
            logger.debug(f"{code} 处理失败: {e}")
        return None
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(process_one, item): item for item in candidates}
        done = 0
        for f in as_completed(futures):
            done += 1
            if done % 10 == 0:
                logger.info(f"进度 {done}/{len(candidates)}, 已耗时 {time.time()-start_t:.0f}s")
            r = f.result()
            if r and r['score'] >= 60:  # 过滤低分
                results.append(r)
    
    logger.info(f"异动识别完成: {len(results)} 只 / 总耗时 {time.time()-start_t:.0f}s")
    
    # Step 5: 排序 + 过滤已存在
    results.sort(key=lambda x: x['score'], reverse=True)
    existing = get_existing_auto_discovered()
    
    new_discoveries = []
    for r in results:
        # 检查冷却期
        is_cooldown, reason = check_cooldown(r['code'])
        if is_cooldown:
            logger.info(f"  跳过 {r['code']} {r['name']}（{reason}）")
            continue
        
        if r['code'] in existing:
            logger.info(f"  跳过 {r['code']} {r['name']}（已在观察池）")
            continue
        new_discoveries.append(r)
        if len(new_discoveries) >= args.top:
            break
    
    logger.info(f"新发现异动: {len(new_discoveries)} 只")
    
    # Step 6: 写入 config.yaml + 数据库
    if new_discoveries:
        for d in new_discoveries:
            add_to_watchlist_history(d['code'], d['name'], d['score'], d['reason'], d['signal_type'])
        
        add_to_config_watchlist(new_discoveries, dry_run=args.dry_run)
        
        # 保存历史
        out_file = OUTPUT_DIR / f"{date.today().isoformat()}_{now.strftime('%H%M')}.json"
        out_file.write_text(json.dumps({
            "timestamp": now.isoformat(),
            "discoveries": new_discoveries,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"已保存 {out_file}")
        
        # Step 7: 推送企微
        if not args.no_webhook:
            md = generate_markdown(now, new_discoveries)
            if push_webhook(md):
                logger.info("✓ 企微推送成功")
        
        # 打印
        print(f"\n🔍 盘中异动 ({now.strftime('%H:%M')}) | 新增 {len(new_discoveries)} 只\n")
        for i, d in enumerate(new_discoveries, 1):
            print(f"{i}. {d['code']} {d['name']:8s} ¥{d['price']:7.2f} {d['pct_chg']:+5.1f}% "
                  f"| {d['signal_type']:20s} | score={d['score']:.0f}")
            print(f"   {d['reason']}")
    else:
        print(f"✓ {now.strftime('%H:%M')} 无新异动")
        logger.info("无新异动")
        # 无异动也推送简短通知
        if not args.no_webhook:
            no_msg = f"✅ 盘中扫描 ({now.strftime('%H:%M')}) | {len(filtered)} 只过滤→{len(candidates)} 只候选→未发现符合条件的异动"
            push_webhook(no_msg)
    
    logger.info(f"=== 盘中异动扫描 结束 ===\n")
    return 0


def generate_markdown(now, discoveries):
    """生成企微 Markdown 消息"""
    md = []
    md.append(f"# 🔍 盘中异动 ({now.strftime('%H:%M')})")
    md.append("")
    md.append(f"**新增观察** {len(discoveries)} 只:")
    md.append("")
    for i, d in enumerate(discoveries, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        line = (f"{emoji} **{d['name']}** ({d['code']}) ¥{d['price']:.2f} "
                f"{d['pct_chg']:+.1f}% | score {d['score']:.0f}")
        md.append(line)
        md.append(f"  - {d['reason']}")
    md.append("")
    md.append("> ⚠️ 系统自动发现，仅供参考。需结合基本面和盘口判断。")
    md.append("> 7 天无触发自动移除。")
    return "\n".join(md)


if __name__ == "__main__":
    sys.exit(main())
