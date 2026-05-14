#!/usr/bin/env python3
"""
scripts/strategy_recommend.py — 综合评分推荐

读取 strategy_pk_summary.csv，按多维度打分给每个策略一个综合分，
推荐"最适合实盘"的策略组合。

评分维度（每项满分 20）：
  1. 收益率（年化收益）
  2. 风险（最大回撤倒数）
  3. 风险调整后收益（夏普比率）
  4. 稳定性（胜率）
  5. 交易频率（接近你的承受范围 - 少而精，过频会增加佣金成本）
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(PROJECT_DIR, "output", "strategy_pk_summary.csv")


def _to_f(v, default=0.0):
    s = str(v).rstrip("%").lstrip("+")
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def score(rec, max_annual, max_dd, max_sharpe, max_win, max_trades):
    """0-20 分"""
    annual = _to_f(rec["年化%"])
    dd = _to_f(rec["最大回撤%"])
    sharpe = _to_f(rec["夏普"])
    win = _to_f(rec["胜率%"])
    trades = int(rec["交易数"])

    # 收益（年化）：按全场最大年化归一化
    s_return = max(0, annual / max(max_annual, 1)) * 20 if max_annual > 0 else 0

    # 回撤（越小越好）：1 - dd/max_dd
    s_risk = (1 - dd / max(max_dd, 1)) * 20 if max_dd > 0 else 20

    # 夏普
    s_sharpe = max(0, sharpe / max(max_sharpe, 0.1)) * 20 if max_sharpe > 0 else 0
    s_sharpe = min(s_sharpe, 20)

    # 胜率
    s_win = (win / 100) * 20

    # 交易频率：理想区间 5-20 笔，少了不够灵活，多了佣金贵
    if 5 <= trades <= 20:
        s_freq = 20
    elif trades < 5:
        s_freq = 10  # 太少
    elif trades <= 30:
        s_freq = 15
    else:
        s_freq = 8  # 太多

    total = s_return + s_risk + s_sharpe + s_win + s_freq
    return {
        "总分": round(total, 1),
        "收益": round(s_return, 1),
        "风险": round(s_risk, 1),
        "夏普": round(s_sharpe, 1),
        "胜率": round(s_win, 1),
        "频率": round(s_freq, 1),
    }


def main():
    if not os.path.exists(CSV_PATH):
        print(f"❌ 没有 PK 结果。先跑 python scripts/strategy_pk.py")
        return

    rows = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("CSV 是空的")
        return

    max_annual = max(_to_f(r["年化%"]) for r in rows)
    max_dd = max(_to_f(r["最大回撤%"]) for r in rows)
    max_sharpe = max(_to_f(r["夏普"]) for r in rows)
    max_win = max(_to_f(r["胜率%"]) for r in rows)
    max_trades = max(int(r["交易数"]) for r in rows)

    scored = []
    for r in rows:
        sc = score(r, max_annual, max_dd, max_sharpe, max_win, max_trades)
        scored.append({**r, **sc})

    scored.sort(key=lambda x: -x["总分"])

    print("=" * 95)
    print(f"{'综合评分推荐（满分 100）':^95}")
    print("=" * 95)
    print(f"{'排名':<4}{'股票':<10}{'策略':<10}{'总分':>6}  收益 风险 夏普 胜率 频率   "
          f"{'年化%':>8}{'回撤%':>8}{'夏普':>6}{'胜率%':>7}{'交易':>5}")
    print("-" * 95)
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(scored):
        medal = medals[i] if i < 3 else "  "
        print(f"{medal:<4}{r['股票']:<10}{r['策略']:<10}{r['总分']:>5.1f}  "
              f"{r['收益']:>4.1f} {r['风险']:>4.1f} {r['夏普']:>4.1f} {r['胜率']:>4.1f} {r['频率']:>4.1f}   "
              f"{r['年化%']:>8}{r['最大回撤%']:>8}{r['夏普']:>6}{r['胜率%']:>7}{r['交易数']:>5}")
    print("=" * 95)

    # 推荐
    top = scored[0]
    print(f"\n🎯 推荐策略：{top['股票']}({top['股票代码']}) × {top['策略']}")
    print(f"   综合评分：{top['总分']}/100")
    print(f"   收益分 {top['收益']}/20、风险分 {top['风险']}/20、夏普分 {top['夏普']}/20、"
          f"胜率分 {top['胜率']}/20、频率分 {top['频率']}/20")

    print("\n💡 解读：")
    print(f"   - 年化收益 {top['年化%']}（基准 3% 国债）")
    print(f"   - 最大回撤 {top['最大回撤%']}（你的 -8% 止损线"
          f"{'够用' if _to_f(top['最大回撤%']) <= 8 else '可能不够（建议放宽到 -10%）'}）")
    print(f"   - 夏普 {top['夏普']}（>1 较好，>2 优秀）")
    print(f"   - {top['交易数']} 笔交易，胜率 {top['胜率%']}")

    print("\n📌 实盘建议（仅参考，不构成投资建议）：")
    print(f"   1. 先用模拟盘跑这个策略 1-2 周，观察信号触发频率")
    print(f"   2. 若一切正常再切 --mode live")
    print(f"   3. 实盘前 50% 资金试水，看回撤可控再加")
    print(f"   4. 注意：A 股市场状态会变，过去回测好不代表未来")


if __name__ == "__main__":
    main()
