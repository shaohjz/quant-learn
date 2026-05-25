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
CONFIG_AUTO_PATH = ROOT / 'config_auto.yaml'


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


def load_config_auto() -> dict:
    """加载 config_auto.yaml（自动管理的观察池）"""
    if not CONFIG_AUTO_PATH.exists():
        return {"auto_discovered": {}, "cooldown": {}}
    try:
        import yaml
        with open(CONFIG_AUTO_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"auto_discovered": {}, "cooldown": {}}
    except Exception:
        return {"auto_discovered": {}, "cooldown": {}}

def load_watchlist_rules(include_disabled: bool = False, category: str = None) -> dict[str, dict]:
    """返回 {code: {'name': str, 'rules': [...], 'category': ...}}
    
    Args:
        include_disabled: 是否包含 enabled=False 的股票
        category: 'user_manual' | 'auto_discovered' | None（None = 全部）
    """
    cfg = load_config()
    watchlist = cfg.get('watchlist', {}) or {}
    
    # 加载 config_auto.yaml
    cfg_auto = load_config_auto()
    
    # 检测是否为新结构（有 user_manual / auto_discovered）
    is_new_structure = 'user_manual' in watchlist or 'auto_discovered' in watchlist
    
    out = {}
    
    if is_new_structure:
        # 新结构：分层观察列表
        categories_to_load = []
        if category is None:
            categories_to_load = ['user_manual', 'auto_discovered']
        elif category in ('user_manual', 'auto_discovered'):
            categories_to_load = [category]
        
        for cat in categories_to_load:
            if cat == 'user_manual':
                # user_manual 从 config.yaml 读
                src = watchlist.get(cat, {}) or {}
            else:
                # auto_discovered 从 config_auto.yaml 读
                src = cfg_auto.get('auto_discovered', {}) or {}
            
            for code, body in src.items():
                if not include_disabled and body.get('enabled', True) is False:
                    continue
                entry = {
                    'name': body.get('name', ''),
                    'rules': _normalize_rules_block(body.get('rules', {})),
                    'category': cat,  # 标记分类
                }
                # 透传 metadata 字段
                for k in ('strategy', 'source', 'recommended_by', 'tags', 'added_at',
                          'added_price', 'added_reason', 'notes', 'discovery_score',
                          'last_alert_at', 'alert_count', 'max_inactive_days', 'signal_type'):
                    if k in body:
                        entry[k] = body[k]
                out[str(code)] = entry
    else:
        # 旧结构（向后兼容）：扁平 watchlist，默认视为 user_manual
        src = watchlist
        for code, body in src.items():
            if not include_disabled and body.get('enabled', True) is False:
                continue
            entry = {
                'name': body.get('name', ''),
                'rules': _normalize_rules_block(body.get('rules', {})),
                'category': 'user_manual',  # 旧结构默认为用户手动
            }
            # 透传 metadata 字段
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
# 观察池更新操作（2026-05-25 新增）
# ============================================================

def update_watchlist_alert(code: str, category: str = 'auto_discovered'):
    """更新观察池股票的告警时间（触发阈值时调用）
    
    Args:
        code: 股票代码
        category: 'user_manual' | 'auto_discovered'
    """
    from datetime import date
    import sqlite3
    
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    today = date.today().isoformat()
    
    # 更新 watchlist_history 的 last_alert_at 和 alert_count
    c.execute("""
        UPDATE watchlist_history
        SET last_alert_at = ?,
            alert_count = alert_count + 1
        WHERE code = ? AND category = ? AND removed_at IS NULL
    """, (today, code, category))
    
    conn.commit()
    conn.close()


def add_to_watchlist(code: str, name: str, category: str, **kwargs):
    """添加股票到观察池（同时更新 config.yaml/config_auto.yaml 和 watchlist_history）
    
    Args:
        code: 股票代码
        name: 股票名称
        category: 'user_manual' | 'auto_discovered'
        **kwargs: 其他元数据（source, added_reason, discovery_score, rules 等）
    """
    import yaml
    import sqlite3
    import json
    from datetime import date
    
    if category == 'user_manual':
        # user_manual 写入 config.yaml
        cfg = load_config()
        if 'watchlist' not in cfg:
            cfg['watchlist'] = {'user_manual': {}, 'auto_discovered': {}}
        if 'user_manual' not in cfg['watchlist']:
            cfg['watchlist']['user_manual'] = {}
        
        cfg['watchlist']['user_manual'][code] = {
            'name': name,
            'enabled': True,
            **kwargs
        }
        
        with open(ROOT / 'config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    else:
        # auto_discovered 写入 config_auto.yaml
        cfg_auto = load_config_auto()
        if 'auto_discovered' not in cfg_auto:
            cfg_auto['auto_discovered'] = {}
        
        cfg_auto['auto_discovered'][code] = {
            'name': name,
            'enabled': True,
            **kwargs
        }
        
        with open(CONFIG_AUTO_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(cfg_auto, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # 2. 更新 watchlist_history
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    today = date.today().isoformat()
    
    metadata = json.dumps({
        'tags': kwargs.get('tags', []),
        'signal_type': kwargs.get('signal_type', ''),
    }, ensure_ascii=False)
    
    c.execute("""
        INSERT OR IGNORE INTO watchlist_history
        (code, name, category, added_at, added_by, added_reason, discovery_score, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        code, name, category, today,
        kwargs.get('added_by', 'system'),
        kwargs.get('added_reason', ''),
        kwargs.get('discovery_score', 0),
        metadata
    ))
    
    conn.commit()
    conn.close()


def remove_from_watchlist(code: str, category: str, reason: str):
    """从观察池移除股票（同时更新 config.yaml/config_auto.yaml 和 watchlist_history）
    
    Args:
        code: 股票代码
        category: 'user_manual' | 'auto_discovered'
        reason: 移除原因（inactive_N_days / trend_broken / user_delete）
    """
    import yaml
    import sqlite3
    from datetime import date
    
    if category == 'user_manual':
        # user_manual 从 config.yaml 删除
        cfg = load_config()
        if 'watchlist' in cfg and 'user_manual' in cfg['watchlist']:
            if code in cfg['watchlist']['user_manual']:
                del cfg['watchlist']['user_manual'][code]
        
        with open(ROOT / 'config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    else:
        # auto_discovered 从 config_auto.yaml 删除
        cfg_auto = load_config_auto()
        if 'auto_discovered' in cfg_auto:
            if code in cfg_auto['auto_discovered']:
                del cfg_auto['auto_discovered'][code]
        
        with open(CONFIG_AUTO_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(cfg_auto, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # 2. 更新 watchlist_history
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    today = date.today().isoformat()
    
    c.execute("""
        UPDATE watchlist_history
        SET removed_at = ?, removed_reason = ?
        WHERE code = ? AND category = ? AND removed_at IS NULL
    """, (today, reason, code, category))
    
    conn.commit()
    conn.close()


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
