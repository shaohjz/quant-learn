"""
scripts/recalibrate_thresholds.py — 用 MA20 + ATR 重新校准 portfolio.yaml 阈值

逻辑：
- 拉每只股票最近 60 交易日日线
- 算 MA20（20 日均线）、ATR14（14 日真实波幅平均）
- 阈值规则：
    持仓股：
      trend_break = MA20  （跌破 20 日线 = 趋势破位）
      take_profit = MA20 + 2.5×ATR （上方 2.5 ATR 处止盈半仓）
    观察股（用现价 vs MA20 判定阶段）：
      buy_zone   = MA20 - 0.5×ATR  （回调到 20 日线下方半个 ATR）
      buy_strong = MA20 - 1.5×ATR  （深度回调）
      trend_break = MA20 - 2.5×ATR （已破位 → 别买）

输出：
- 新 portfolio.yaml.calibrated（不直接覆盖，留底）
- 打印对比表：旧阈值 vs 新阈值
"""
import sys, os
from pathlib import Path
import yaml
from copy import deepcopy
from datetime import date, timedelta
import logging

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('recal')

CONFIG_IN = ROOT / 'vqlearn' / 'config' / 'portfolio.yaml'
CONFIG_OUT = ROOT / 'vqlearn' / 'config' / 'portfolio.calibrated.yaml'


def fetch_klines(code: str, days: int = 60) -> list:
    import akshare as ak
    end = date.today().strftime('%Y%m%d')
    start = (date.today() - timedelta(days=days*2)).strftime('%Y%m%d')
    # 首选新浪源，退化到东财
    if code.startswith(('60', '68', '11', '12', '5')):
        sina_code = 'sh' + code
    elif code.startswith(('00', '30', '15', '16')):
        sina_code = 'sz' + code
    else:
        sina_code = 'sh' + code
    try:
        df = ak.stock_zh_a_daily(symbol=sina_code, start_date=start, end_date=end, adjust='qfq')
        if df is None or len(df) < 20:
            raise ValueError(f'新浪数据不够: {len(df) if df is not None else 0}')
        # 重命名列以适配 calc_ma_atr
        df = df.rename(columns={'close': '收盘', 'high': '最高', 'low': '最低', 'open': '开盘', 'volume': '成交量'})
        return df.tail(days).to_dict('records')
    except Exception as e1:
        try:
            df = ak.stock_zh_a_hist(symbol=code, period='daily', adjust='qfq', start_date=start, end_date=end)
            if df is None or len(df) < 20:
                logger.warning(f'{code} 两路都不够, sina={e1}')
                return []
            return df.tail(days).to_dict('records')
        except Exception as e2:
            logger.warning(f'{code} 拉数据失败 sina={e1} em={e2}')
            return []


def calc_ma_atr(klines: list) -> tuple[float, float, float]:
    """返回 (last_close, ma20, atr14)"""
    if len(klines) < 20:
        return 0, 0, 0
    closes = [float(k['收盘']) for k in klines]
    highs = [float(k['最高']) for k in klines]
    lows = [float(k['最低']) for k in klines]

    ma20 = sum(closes[-20:]) / 20

    # ATR14
    trs = []
    for i in range(1, len(klines)):
        h, l = highs[i], lows[i]
        pc = closes[i-1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr14 = sum(trs[-14:]) / 14 if len(trs) >= 14 else (sum(trs)/len(trs) if trs else 0)
    return closes[-1], ma20, atr14


def round_tick(x: float) -> float:
    """A 股最小变动 0.01"""
    return round(x, 2)


def main():
    cfg = yaml.safe_load(CONFIG_IN.read_text(encoding='utf-8'))
    new_cfg = deepcopy(cfg)
    table = []

    def process_group(group_name: str, items: list, is_holding: bool):
        for item in items:
            code = item['symbol']
            name = item.get('name', code)
            klines = fetch_klines(code, days=60)
            last, ma20, atr = calc_ma_atr(klines)
            if ma20 == 0:
                logger.warning(f'{code} {name} 数据不够，跳过')
                continue

            old_rules = item.get('rules', {}) or {}
            new_rules = {}

            if is_holding:
                new_rules['trend_break'] = round_tick(ma20 * 0.99)  # MA20 下方 1%（缓冲）
                new_rules['take_profit'] = round_tick(ma20 + 2.5 * atr)
                # 不设 buy_zone/buy_strong（持仓股不抄自己）
            else:
                new_rules['buy_zone'] = round_tick(ma20 - 0.5 * atr)
                new_rules['buy_strong'] = round_tick(ma20 - 1.5 * atr)
                new_rules['trend_break'] = round_tick(ma20 - 2.5 * atr)

            row = {
                'group': group_name,
                'code': code, 'name': name,
                'last': last, 'ma20': round_tick(ma20), 'atr14': round_tick(atr),
                'old_buy_zone': old_rules.get('buy_zone', '-'),
                'new_buy_zone': new_rules.get('buy_zone', '-'),
                'old_buy_strong': old_rules.get('buy_strong', '-'),
                'new_buy_strong': new_rules.get('buy_strong', '-'),
                'old_trend_break': old_rules.get('trend_break', '-'),
                'new_trend_break': new_rules.get('trend_break', '-'),
                'old_take_profit': old_rules.get('take_profit', '-'),
                'new_take_profit': new_rules.get('take_profit', '-'),
            }
            table.append(row)
            item['rules'] = new_rules

    process_group('holdings', new_cfg.get('holdings', []), is_holding=True)
    process_group('watchlist', new_cfg.get('watchlist', []), is_holding=False)

    # 打印对比表
    print()
    print(f"{'代码':<8} {'名称':<10} {'last':>7} {'MA20':>7} {'ATR':>5}  | {'旧 buy_z':>8} → {'新 buy_z':>8} | {'旧 buy_s':>8} → {'新 buy_s':>8} | {'旧 trend':>8} → {'新 trend':>8} | {'旧 tp':>7} → {'新 tp':>7}")
    print('-' * 170)
    for r in table:
        print(f"{r['code']:<8} {r['name']:<10} {r['last']:>7.2f} {r['ma20']:>7.2f} {r['atr14']:>5.2f}  | "
              f"{str(r['old_buy_zone']):>8} → {str(r['new_buy_zone']):>8} | "
              f"{str(r['old_buy_strong']):>8} → {str(r['new_buy_strong']):>8} | "
              f"{str(r['old_trend_break']):>8} → {str(r['new_trend_break']):>8} | "
              f"{str(r['old_take_profit']):>7} → {str(r['new_take_profit']):>7}")

    # 保存
    CONFIG_OUT.write_text(yaml.safe_dump(new_cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f'\n✅ 校准结果已写入: {CONFIG_OUT}')
    print(f'   原文件不动: {CONFIG_IN}')
    print(f'   核对无误后手动 mv 替换')


if __name__ == '__main__':
    main()
