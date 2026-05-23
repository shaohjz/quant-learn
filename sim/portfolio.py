"""
sim/portfolio.py — 持仓 / 阈值规则 / 双账户的统一加载器
（2026-05-22 单一真源重构）

数据流:
  config.yaml (real_portfolio_rules + watchlist)  ←  规则真源
  sim_live_mirror.db (sim_positions)              ←  实时持仓真源（数量/成本/现价）

调用方应该:
  - 用 load_real_holdings() 拿到真实持仓的「实时数量+成本」+「告警规则」
  - 用 load_watchlist() 拿到观察池的「阈值规则」
  - 用 load_accounts_meta() 拿到账户元数据
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from sim.config import load_config

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'data' / 'sim_live_mirror.db'


# ============================================================
# 账户元数据
# ============================================================

def load_accounts_meta() -> dict:
    """返回 {'learn': {...}, 'real': {...}}"""
    cfg = load_config()
    return cfg.get('accounts', {}) or {}


def real_account_id() -> int:
    return int(load_accounts_meta().get('real', {}).get('account_id', 2))


def learn_account_id() -> int:
    return int(load_accounts_meta().get('learn', {}).get('account_id', 1))


def learn_max_total_value() -> float:
    return float(load_accounts_meta().get('learn', {}).get('max_total_value', 100000.0))


# ============================================================
# 持仓查询（数据库为准）
# ============================================================

def _connect_ro():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def fetch_positions(account_id: int) -> list[dict]:
    """从 sim_positions 拉指定账户的持仓"""
    c = _connect_ro()
    rows = c.execute(
        "SELECT stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct, updated_at "
        "FROM sim_positions WHERE account_id=? AND quantity > 0 ORDER BY market_value DESC",
        (account_id,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_account(account_id: int) -> dict | None:
    c = _connect_ro()
    r = c.execute(
        "SELECT id, account_name, initial_cash, cash, total_value, updated_at "
        "FROM sim_account WHERE id=?",
        (account_id,)
    ).fetchone()
    c.close()
    return dict(r) if r else None


# ============================================================
# 规则加载（config.yaml 为准）
# ============================================================

def _normalize_rules_block(block: dict) -> list[dict]:
    """把 yaml 里的 {level: {trigger,dir,msg}} 摊平成
       [{level, trigger, dir, msg}, ...]"""
    out = []
    for level, body in (block or {}).items():
        if not isinstance(body, dict):
            continue
        out.append({
            'level': level,
            'trigger': float(body.get('trigger', 0)),
            'dir': body.get('dir', 'below'),
            'msg': body.get('msg', ''),
        })
    return out


def load_real_holdings_rules() -> dict[str, dict]:
    """返回 {code: {'name': str, 'rules': [...]}}（仅规则部分，不含数量/成本）"""
    cfg = load_config()
    src = cfg.get('real_portfolio_rules', {}) or {}
    out = {}
    for code, body in src.items():
        out[str(code)] = {
            'name': body.get('name', ''),
            'rules': _normalize_rules_block(body.get('rules', {})),
        }
    return out


def load_watchlist_rules(include_disabled: bool = False) -> dict[str, dict]:
    """返回 {code: {'name': str, 'rules': [...], 'strategy': ...}}"""
    cfg = load_config()
    src = cfg.get('watchlist', {}) or {}
    out = {}
    for code, body in src.items():
        if not include_disabled and body.get('enabled', True) is False:
            continue
        entry = {
            'name': body.get('name', ''),
            'rules': _normalize_rules_block(body.get('rules', {})),
        }
        # 透传 metadata 字段（strategy/source/tags 等）
        for k in ('strategy', 'source', 'recommended_by', 'tags', 'added_at',
                  'added_price', 'added_reason', 'notes'):
            if k in body:
                entry[k] = body[k]
        out[str(code)] = entry
    return out


# ============================================================
# 综合视图：真实账户「持仓 + 规则」
# ============================================================

def load_real_holdings() -> list[dict]:
    """返回真实账户持仓的综合视图：
    [{code, name, qty, cost, current, market_value, pnl, pnl_pct, rules: [...]}]
    持仓数据来自 db；规则来自 config.yaml；二者用 code 关联。
    """
    rules_by_code = load_real_holdings_rules()
    positions = fetch_positions(real_account_id())
    out = []
    for p in positions:
        code = p['stock_code']
        rules_meta = rules_by_code.get(code, {})
        out.append({
            'code': code,
            'name': p['stock_name'] or rules_meta.get('name', ''),
            'qty': p['quantity'],
            'cost': p['avg_cost'],
            'current': p['current_price'],
            'market_value': p['market_value'],
            'pnl': p['pnl'],
            'pnl_pct': p['pnl_pct'],
            'rules': rules_meta.get('rules', []),
            'updated_at': p['updated_at'],
        })
    return out


def load_all_alert_rules(include_watchlist: bool = True) -> list[dict]:
    """供 portfolio_alert.py 用的扁平 RULES 列表（兼容老格式）：
    [{code, name, level, trigger, dir, message, source: 'real'|'watchlist'}]
    """
    out = []
    # 持仓股
    for h in load_real_holdings():
        for r in h['rules']:
            out.append({
                'code': h['code'], 'name': h['name'], 'level': r['level'],
                'trigger': r['trigger'], 'dir': r['dir'],
                'message': r['msg'], 'source': 'real',
            })
    # 观察池
    if include_watchlist:
        for code, body in load_watchlist_rules().items():
            for r in body['rules']:
                out.append({
                    'code': code, 'name': body['name'], 'level': r['level'],
                    'trigger': r['trigger'], 'dir': r['dir'],
                    'message': r['msg'], 'source': 'watchlist',
                })
    return out


def all_codes_to_subscribe() -> list[str]:
    """所有需要订阅行情的股票代码（持仓 + 观察池）"""
    codes = set()
    for h in load_real_holdings():
        codes.add(h['code'])
    for code in load_watchlist_rules().keys():
        codes.add(code)
    return sorted(codes)


# ============================================================
# CLI 自检
# ============================================================
if __name__ == '__main__':
    print('=== 账户元数据 ===')
    for k, v in load_accounts_meta().items():
        print(f'  {k}: {v}')

    print('\n=== 真实账户持仓（来自 db, 规则来自 config.yaml）===')
    for h in load_real_holdings():
        print(f"  {h['code']} {h['name']:<6} qty={h['qty']:>4} cost={h['cost']:>7.3f} "
              f"cur={h['current']:>7.3f} mv={h['market_value']:>9.2f} "
              f"pnl={h['pnl']:+.2f}({h['pnl_pct']:+.2f}%) rules={len(h['rules'])}")

    print('\n=== 观察池（启用）===')
    for code, body in load_watchlist_rules().items():
        print(f"  {code} {body['name']:<6} rules={len(body['rules'])}")

    print('\n=== 全部告警规则（扁平视图） ===')
    for r in load_all_alert_rules():
        print(f"  [{r['source']:9s}] {r['code']} {r['name']:<6} {r['level']:18s} "
              f"{r['dir']} {r['trigger']:>7.2f}  {r['message'][:30]}")

    print(f"\n=== 全部需订阅代码: {all_codes_to_subscribe()}")
