"""
Supertrend 回测 - 使用新浪财经免费接口
"""
import requests
import pandas as pd
import numpy as np
import os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ATR_PERIOD = 10
MULTIPLIER = 3.0
START_DATE = "2025-01-01"
END_DATE = "2026-06-09"

STOCK_CODES = [
    "sh600519", "sz000858", "sz002415", "sh600036", "sz000333",
    "sh600310", "sh600130", "sz001896", "sh603178", "sz000899",
    "sh600330",
    "sh601318", "sh600900", "sz300750", "sz000651", "sh600887",
    "sh601166", "sh600585", "sz000002", "sh600276", "sz000568",
    "sh600809", "sz002594", "sz000725", "sh600030", "sz002142",
    "sh601398", "sh601288", "sz000063", "sh600703", "sz002049",
    "sz300059", "sh600570", "sz002230", "sz300015", "sz000538",
    "sh601899", "sz002460", "sh600547", "sz002304", "sh601012",
    "sh600438", "sz002371", "sh603986", "sz300124", "sh600031"
]


def fetch_sina_kline(code):
    """从新浪财经获取日K线"""
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=60&ma=no&datalen=1023"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['day'])
        df = df.rename(columns={'open':'open','high':'high','low':'low','close':'close','volume':'volume'})
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
        df = df.set_index('date').sort_index()
        return df
    except:
        return None


def calc_supertrend(df, period=10, multiplier=3.0):
    df = df.copy().sort_index()
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = (df['high'] - df['prev_close']).abs()
    df['tr3'] = (df['low'] - df['prev_close']).abs()
    df['tr'] = df[['tr1','tr2','tr3']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    df['hl2'] = (df['high'] + df['low']) / 2
    df['basic_up'] = df['hl2'] - multiplier * df['atr']
    df['basic_dn'] = df['hl2'] + multiplier * df['atr']

    final_up = np.full(len(df), np.nan)
    final_dn = np.full(len(df), np.nan)
    trend = np.full(len(df), 1)

    for i in range(1, len(df)):
        if np.isnan(final_up[i-1]):
            final_up[i] = df['basic_up'].iloc[i]
        else:
            final_up[i] = max(df['basic_up'].iloc[i], final_up[i-1]) if df['close'].iloc[i-1] > final_up[i-1] else df['basic_up'].iloc[i]
        if np.isnan(final_dn[i-1]):
            final_dn[i] = df['basic_dn'].iloc[i]
        else:
            final_dn[i] = min(df['basic_dn'].iloc[i], final_dn[i-1]) if df['close'].iloc[i-1] < final_dn[i-1] else df['basic_dn'].iloc[i]
        if trend[i-1] == -1 and df['close'].iloc[i] > final_dn[i-1]:
            trend[i] = 1
        elif trend[i-1] == 1 and df['close'].iloc[i] < final_up[i-1]:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]

    df['trend'] = trend
    df['buy_signal'] = (df['trend'] == 1) & (df['trend'].shift(1) == -1)
    df['sell_signal'] = (df['trend'] == -1) & (df['trend'].shift(1) == 1)
    return df


def backtest(df, code):
    df = calc_supertrend(df).dropna(subset=['atr'])
    trades = []
    in_pos = False
    for i in range(1, len(df)):
        if not in_pos and df['buy_signal'].iloc[i] and i+1 < len(df):
            entry_p = df['open'].iloc[i+1]
            entry_d = df.index[i+1]
            in_pos = True
        elif in_pos and df['sell_signal'].iloc[i] and i+1 < len(df):
            exit_p = df['open'].iloc[i+1]
            exit_d = df.index[i+1]
            pnl = (exit_p - entry_p) / entry_p * 100
            trades.append({'code': code, 'entry': entry_d, 'exit': exit_d,
                           'entry_p': round(entry_p,2), 'exit_p': round(exit_p,2),
                           'pnl': round(pnl,2), 'days': (exit_d-entry_d).days, 'win': 1 if pnl>0 else 0})
            in_pos = False
    if in_pos:
        pnl = (df['close'].iloc[-1] - entry_p) / entry_p * 100
        trades.append({'code': code, 'entry': entry_d, 'exit': df.index[-1],
                       'entry_p': round(entry_p,2), 'exit_p': round(df['close'].iloc[-1],2),
                       'pnl': round(pnl,2), 'days': (df.index[-1]-entry_d).days, 'win': 1 if pnl>0 else 0})
    return trades


def main():
    print("=" * 60)
    print("Supertrend 回测 (新浪财经)")
    print(f"参数: ATR={ATR_PERIOD}, Mult={MULTIPLIER}")
    print(f"股票: {len(STOCK_CODES)} 只")
    print("=" * 60)

    all_trades = []
    success = 0
    fail = 0

    for code in STOCK_CODES:
        try:
            df = fetch_sina_kline(code)
            if df is None or len(df) < 30:
                fail += 1
                continue
            trades = backtest(df, code)
            all_trades.extend(trades)
            if trades:
                success += 1
                print(f"  {code}: {len(trades)} 笔")
            else:
                fail += 1
            time.sleep(0.2)
        except:
            fail += 1

    if not all_trades:
        print("\n❌ 无交易")
        return

    df = pd.DataFrame(all_trades)
    total = len(df)
    wins = df['win'].sum()
    losses = total - wins
    wr = wins/total*100
    avg_w = df[df['win']==1]['pnl'].mean() if wins>0 else 0
    avg_l = df[df['win']==0]['pnl'].mean() if losses>0 else 0
    pf = abs(avg_w*wins/(avg_l*losses)) if avg_l!=0 and losses>0 else float('inf')

    df_sorted = df.sort_values('exit')
    df_sorted['cum'] = (1+df_sorted['pnl']/100).cumprod()
    df_sorted['peak'] = df_sorted['cum'].cummax()
    df_sorted['dd'] = (df_sorted['cum']-df_sorted['peak'])/df_sorted['peak']*100
    mdd = df_sorted['dd'].min()

    streak = 0; max_streak = 0
    for w in df['win']:
        if w==0: streak+=1; max_streak=max(max_streak,streak)
        else: streak=0

    print(f"\n{'='*60}")
    print(f"📊 回测结果")
    print(f"{'='*60}")
    print(f"股票: {success}只成功 / {fail}只失败")
    print(f"交易: {total}笔")
    print(f"胜率: {wr:.1f}%")
    print(f"平均收益: {df['pnl'].mean():.2f}%")
    print(f"平均盈利: {avg_w:.2f}%")
    print(f"平均亏损: {avg_l:.2f}%")
    print(f"盈亏比: {abs(avg_w/avg_l):.2f}" if avg_l!=0 else "盈亏比: ∞")
    print(f"利润因子: {pf:.2f}")
    print(f"最大盈利: {df['pnl'].max():.2f}%")
    print(f"最大亏损: {df['pnl'].min():.2f}%")
    print(f"平均持仓: {df['days'].mean():.0f}天")
    print(f"最大回撤: {mdd:.1f}%")
    print(f"最大连亏: {max_streak}次")

    print(f"\n📊 收益分布")
    bins = [-100, -10, -5, -2, 0, 2, 5, 10, 100]
    labels = ['<-10%','-10~-5%','-5~-2%','-2~0%','0~2%','2~5%','5~10%','>10%']
    df['bin'] = pd.cut(df['pnl'], bins=bins, labels=labels)
    dist = df['bin'].value_counts().sort_index()
    mc = max(dist)
    for k,v in dist.items():
        print(f"  {k:>8}: {v:>3}笔 {'█'*int(v/mc*30)}")

    by_stock = df.groupby('code').agg(
        次数=('pnl','count'),
        胜率=('win', lambda x: f"{x.mean()*100:.0f}%"),
        平均收益=('pnl', lambda x: f"{x.mean():.1f}%"),
        总收益=('pnl', lambda x: f"{x.sum():.1f}%")
    ).sort_values('次数', ascending=False)
    print(f"\n📈 按股票（前15）")
    print(by_stock.head(15).to_string())

    df['month'] = pd.to_datetime(df['exit']).dt.to_period('M')
    monthly = df.groupby('month').agg(
        次数=('pnl','count'),
        胜率=('win', lambda x: f"{x.mean()*100:.0f}%"),
        月收益=('pnl', lambda x: f"{x.sum():.1f}%")
    )
    print(f"\n📅 按月")
    print(monthly.to_string())

    print(f"\n{'='*60}")
    print(f"🔍 结论")
    print(f"{'='*60}")
    if wr > 50: print(f"✅ 胜率 {wr:.1f}% > 50%")
    else: print(f"❌ 胜率 {wr:.1f}% < 50%")
    if pf > 1.5: print(f"✅ 利润因子 {pf:.2f} > 1.5")
    elif pf > 1.0: print(f"⚠️ 利润因子 {pf:.2f} > 1.0")
    else: print(f"❌ 利润因子 {pf:.2f} < 1.0")
    if max_streak >= 5: print(f"⚠️ 最大连亏 {max_streak}次")
    if mdd < -20: print(f"⚠️ 最大回撤 {mdd:.1f}%")
    if df['days'].mean() < 5: print(f"💡 短线指标，均持{df['days'].mean():.0f}天")

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "backtest_supertrend.csv")
    df.to_csv(out, index=False, encoding='utf-8-sig')
    print(f"\n📁 保存到: {out}")


if __name__ == "__main__":
    main()
