#!/usr/bin/env python
"""
scripts/morning_scanner.py — 每日 8:30 盘前股票池扫描

目标：
  - 拉取沪深300 + 中证500 成分股（约800只）
  - 按多因子打分 → 输出 Top 10 候选
  - 推送到企微群（开盘前可看）
  - 写入本地 output/scan/ 历史记录

打分因子（每项 0~25 分，满分 100）：
  1. 趋势强度    : 价格 vs MA5/MA10/MA20 多头排列程度
  2. 突破信号    : 最近5日是否有量价配合突破前高
  3. 量能放大    : 当日成交量 vs 5日均量
  4. 短期超跌反弹: RSI 是否处于回升区间（避免追高）

风险过滤（直接 PASS）：
  - 涨幅 > 7%（追高风险大）
  - 跌幅 > 7%（恐慌盘）
  - 成交额 < 1亿（流动性差）
  - ST / *ST 股票（名称含 ST）
  - 价格 > 500（单手太贵）

用法：
  python scripts/morning_scanner.py        # 用默认股票池
  python scripts/morning_scanner.py --top 20  # 推前20只
"""
import os
import sys
import json
import logging
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT / "output" / "scan"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ====================================================================
#  Webhook
# ====================================================================
def _load_webhook():
    try:
        import yaml
        cfg = ROOT / "config.local.yaml"
        if cfg.exists():
            d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
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
#  股票池
# ====================================================================
def get_universe():
    """获取股票池：沪深300 + 中证500"""
    import akshare as ak
    
    codes = set()
    try:
        df_300 = ak.index_stock_cons(symbol="000300")
        codes.update(df_300["品种代码"].astype(str).tolist())
        logger.info(f"沪深300: {len(df_300)} 只")
    except Exception as e:
        logger.warning(f"拉沪深300 失败: {e}")
    
    try:
        df_500 = ak.index_stock_cons(symbol="000905")
        codes.update(df_500["品种代码"].astype(str).tolist())
        logger.info(f"中证500: {len(df_500)} 只")
    except Exception as e:
        logger.warning(f"拉中证500 失败: {e}")
    
    return sorted(codes)


# ====================================================================
#  数据拉取（一次拉所有股票当日 + 历史价格）
# ====================================================================
def fetch_all_realtime():
    """拉取全市场实时行情。优先东财，失败后用新浪，再不行就为股池中的股票逐只拉。"""
    import akshare as ak
    last_err = None
    # 尝试东财
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    logger.warning(f"东财 spot_em 失败: {last_err}，切新浪")
    # 尝试新浪的全市场接口
    try:
        df = ak.stock_zh_a_spot()
        # 新浪字段名不同，需重命名适配东财格式
        if df is not None and len(df) > 0:
            df = df.rename(columns={
                "code": "代码", "symbol": "代码",
                "name": "名称",
                "trade": "最新价", "price": "最新价",
                "changepercent": "涨跌幅", "pct_chg": "涨跌幅",
                "amount": "成交额",
            })
            # 新浪代码带 sh/sz 前缀，去掉
            df["代码"] = df["代码"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)
            return df
    except Exception as e:
        logger.error(f"新浪 spot 也失败: {e}")
    raise RuntimeError("东财和新浪实时行情接口均失败")


def calc_factors(code: str, hist_df, spot_row):
    """计算单只股票打分（0-100）"""
    if hist_df is None or len(hist_df) < 20:
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
    avg_vol5 = v.tail(5).mean()
    today_vol = float(v.iloc[-1])
    high20 = h.tail(20).max()
    
    # 因子1: 趋势强度（多头排列）
    trend_score = 0
    if last > ma5: trend_score += 6
    if ma5 > ma10: trend_score += 6
    if ma10 > ma20: trend_score += 6
    if last > ma20: trend_score += 7
    # max 25
    
    # 因子2: 突破信号（5日内创新高 + 站稳）
    breakout_score = 0
    last5_high = h.tail(5).max()
    if last5_high >= high20 * 0.99:  # 接近20日高
        breakout_score += 15
    if last >= ma5:
        breakout_score += 5
    if last >= last5_high * 0.97:  # 当前价仍接近5日高（没回吐）
        breakout_score += 5
    # max 25
    
    # 因子3: 量能配合（量比 = 当日量 / 5日均量）
    vol_ratio = today_vol / avg_vol5 if avg_vol5 > 0 else 0
    if vol_ratio >= 2.0:
        vol_score = 25
    elif vol_ratio >= 1.5:
        vol_score = 20
    elif vol_ratio >= 1.2:
        vol_score = 15
    elif vol_ratio >= 1.0:
        vol_score = 10
    else:
        vol_score = 5
    # max 25
    
    # 因子4: 涨幅区间合理性（避免追高）
    pct_chg = (last / float(c.iloc[-2]) - 1) * 100 if len(c) >= 2 else 0
    if 0 < pct_chg <= 3:
        zone_score = 25  # 温和上涨最佳
    elif 3 < pct_chg <= 5:
        zone_score = 20
    elif -2 <= pct_chg <= 0:
        zone_score = 15  # 平盘略跌也能选
    elif 5 < pct_chg <= 7:
        zone_score = 10  # 涨幅偏大
    else:
        zone_score = 5
    # max 25
    
    total = trend_score + breakout_score + vol_score + zone_score
    
    return {
        "code": code,
        "price": last,
        "pct_chg": pct_chg,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "vol_ratio": vol_ratio,
        "score": total,
        "factors": {
            "trend": trend_score,
            "breakout": breakout_score,
            "volume": vol_score,
            "zone": zone_score,
        }
    }


def get_kline(code: str, days: int = 30, retries: int = 3):
    """拉单只 K 线（带重试），由于akshare在云桌面限流，切换到baostock"""
    import baostock as bs
    import pandas as pd
    from datetime import datetime, timedelta
    
    bs.login() # 确保已登录
    
    # 转换股票代码格式，baostock需要sh/sz前缀
    bs_code = f"sh.{code}" if code.startswith("6") else f"sz.{code}"
    
    start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    last_err = None
    for attempt in range(retries):
        try:
            rs = bs.query_history_k_data_plus(bs_code,
                "date,code,open,high,low,close,volume,amount,adjustflag",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2") # 2 = 前复权
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return None
                
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # baostock返回的是字符串，需要转换，且处理停牌空字符串
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna()
            
            # 为了适配现有的 calc_factors
            df = df.rename(columns={
                "close": "收盘",
                "volume": "成交量",
                "high": "最高",
                "low": "最低",
                "open": "开盘",
                "date": "日期"
            })
            
            # bs.logout() # 退出移到脚本结尾比较好，但为了简单这里就不频繁开关了。由全局处理或者只开一次更好。
            
            return df.tail(days).reset_index(drop=True)
            
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))  # 退避
    logger.debug(f"{code} 拉K线失败（3次）: {last_err}")
    return None


def filter_universe(codes, spot_df):
    """对股票池做风险过滤，先减少要拉K线的数量"""
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
        
        if price <= 0 or price > 500:
            continue
        if abs(pct) > 7:
            continue
        if amount < 1e8:
            continue
        
        filtered.append({"code": code, "name": name, "price": price, "pct": pct, "amount": amount})
    
    return filtered


# ====================================================================
#  主流程
# ====================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=10, help="返回 Top N")
    parser.add_argument("--limit", type=int, default=0, help="限制扫描数量（0=全部，调试用）")
    parser.add_argument("--no-webhook", action="store_true", help="不推送企微")
    args = parser.parse_args()
    
    today = date.today()
    logger.info(f"=== Morning Scanner 开始 {today} ===")
    
    # Step 1: 获取股票池
    universe = get_universe()
    logger.info(f"股票池: {len(universe)} 只")
    
    # Step 2: 拉全市场实时行情（一次性，不要循环）
    logger.info("拉全市场实时行情...")
    spot_df = fetch_all_realtime()
    logger.info(f"实时行情: {len(spot_df)} 条")
    
    # Step 3: 风险过滤
    filtered = filter_universe(universe, spot_df)
    logger.info(f"过滤后剩余: {len(filtered)} 只")
    
    if args.limit > 0:
        filtered = filtered[:args.limit]
        logger.info(f"调试模式限制 {len(filtered)} 只")
    
    # Step 4: 拉 K 线 + 计算评分（多线程，但限速）
    results = []
    start_t = time.time()
    
    def process_one(item):
        code = item["code"]
        try:
            df = get_kline(code, days=30)
            if df is None:
                return None
            score = calc_factors(code, df, item)
            if score:
                score["name"] = item["name"]
                score["amount"] = item["amount"]
                return score
        except Exception as e:
            logger.debug(f"{code} 处理失败: {e}")
        return None
    
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(process_one, item): item for item in filtered}
        done = 0
        for f in as_completed(futures):
            done += 1
            if done % 50 == 0:
                logger.info(f"进度 {done}/{len(filtered)}, 已耗时 {time.time()-start_t:.0f}s")
            r = f.result()
            if r:
                results.append(r)
    
    logger.info(f"评分完成: {len(results)} 只 / 总耗时 {time.time()-start_t:.0f}s")
    
    # Step 5: 排序 Top N
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:args.top]
    
    # Step 6: 保存历史
    out_file = OUTPUT_DIR / f"{today.isoformat()}.json"
    out_file.write_text(json.dumps({
        "date": today.isoformat(),
        "universe_size": len(universe),
        "filtered_size": len(filtered),
        "scored_size": len(results),
        "top": top,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"已保存 {out_file}")
    
    # Step 7: 推送企微
    if not args.no_webhook and top:
        md = generate_markdown(today, top, len(universe), len(filtered), len(results))
        if push_webhook(md):
            logger.info("✓ 企微推送成功")
        else:
            logger.warning("企微推送失败")
    
    # 打印 Top
    print(f"\n=== Top {len(top)} ===")
    for i, r in enumerate(top, 1):
        f = r["factors"]
        print(f"{i:2d}. {r['code']} {r['name']:8s} {r['price']:7.2f} {r['pct_chg']:+5.1f}% "
              f"评分={r['score']:.0f} 量比={r['vol_ratio']:.1f} "
              f"[趋势{f['trend']} 突破{f['breakout']} 量能{f['volume']} 区间{f['zone']}]")


def generate_markdown(today, top, n_universe, n_filtered, n_scored):
    md = []
    md.append(f"# 📊 {today.year}/{today.month}/{today.day} 盘前选股")
    md.append("")
    md.append(f"**池**: 沪深300 + 中证500 ({n_universe}只) / 过滤后 {n_filtered} / 评分 {n_scored}")
    md.append("")
    md.append("**Top 候选** (基于4因子打分: 趋势/突破/量能/区间，仅供参考):")
    md.append("")
    for i, r in enumerate(top, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        f = r["factors"]
        line = (f"{emoji} **{r['name']}** ({r['code']}) ¥{r['price']:.2f} "
                f"{r['pct_chg']:+.1f}% | 评分 {r['score']:.0f} | "
                f"量比 {r['vol_ratio']:.1f}")
        md.append(line)
        md.append(f"  - 趋势 {f['trend']} / 突破 {f['breakout']} / 量能 {f['volume']} / 区间 {f['zone']}")
    md.append("")
    md.append("> ⚠️ 仅为评分排序，**不是买入建议**。需结合板块、个股逻辑、风险点综合判断。")
    md.append("> 加入观察池请回复：「加 XXXXXX」")
    return "\n".join(md)


if __name__ == "__main__":
    main()
