#!/usr/bin/env python3
"""
scripts/fetch_sector.py — 获取A股股票行业/板块归属

数据源：AKShare (ak.stock_individual_info_em — 东方财富个股信息)
缓存策略：写入 data/sector_cache.json，按 stock_code 索引
         过期时间：7 天（避免频繁请求 API）

用法：
  python scripts/fetch_sector.py              # 更新所有持仓 + 观察池股票的行业信息
  python scripts/fetch_sector.py 600309 002709  # 指定股票代码
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_FILE = ROOT / "output" / "sector_cache.json"
CACHE_TTL_DAYS = 7

# AKShare 可能返回的"行业"字段名（不同版本有差异）
_INDUSTRY_KEYS = ["行业", "所属行业", "industry", "Industry"]
_SECTOR_KEYS = ["板块", "所属板块", "sector", "Sector"]


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "updated_at": None, "data": {}}


def _save_cache(cache: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _is_expired(ts_str: str | None) -> bool:
    if not ts_str:
        return True
    try:
        ts = datetime.fromisoformat(ts_str)
        return datetime.now() - ts > timedelta(days=CACHE_TTL_DAYS)
    except ValueError:
        return True


def fetch_stock_info_akshare(stock_code: str) -> dict | None:
    """
    用 AKShare 获取单只股票的行业/板块信息。
    返回 {"code": ..., "name": ..., "industry": ..., "sector": ..., "concept": [...]}
    """
    try:
        import akshare as ak
    except ImportError:
        print("  ❌ 需要安装 akshare: pip install akshare")
        return None

    # 规范化代码：AKShare 需要带市场前缀或纯数字
    # stock_individual_info_em 接受 6 位数字代码
    code_6 = stock_code.zfill(6)

    try:
        # 方法1：东方财富个股信息（含行业）
        df = ak.stock_individual_info_em(symbol=code_6)
        if df is None or df.empty:
            return None

        info = {}
        for _, row in df.iterrows():
            key = str(row.get("item", row.get("key", ""))).strip()
            val = str(row.get("value", row.get("val", ""))).strip()
            info[key] = val

        industry = info.get("行业", info.get("所属行业", ""))
        sector = info.get("板块", info.get("所属板块", ""))
        name = info.get("股票简称", info.get("名称", ""))

        return {
            "code": stock_code,
            "name": name,
            "industry": industry,
            "sector": sector,
            "raw": info,
        }

    except Exception as e:
        # 方法2：回退到 stock_zh_a_spot_em 获取板块信息
        try:
            df_spot = ak.stock_zh_a_spot_em()
            row = df_spot[df_spot["代码"] == code_6]
            if not row.empty:
                r = row.iloc[0]
                return {
                    "code": stock_code,
                    "name": str(r.get("名称", "")),
                    "industry": "",
                    "sector": str(r.get("板块", r.get("所属板块", ""))),
                    "raw": dict(r),
                }
        except Exception:
            pass
        print(f"  ⚠️  获取 {stock_code} 行业信息失败: {e}")
        return None


def fetch_sector_concept_akshare(stock_code: str) -> list[str]:
    """
    获取股票的概念板块列表（用于更细粒度分析）。
    使用 ak.stock_board_concept_name_em + ak.stock_board_concept_cons_em
    """
    try:
        import akshare as ak
    except ImportError:
        return []

    code_6 = stock_code.zfill(6)
    concepts = []
    try:
        # 获取所有概念板块列表
        df_concepts = ak.stock_board_concept_name_em()
        for _, row in df_concepts.iterrows():
            concept_name = row.get("板块名称", row.get("name", ""))
            try:
                df_cons = ak.stock_board_concept_cons_em(symbol=concept_name)
                if code_6 in df_cons["代码"].values:
                    concepts.append(str(concept_name))
            except Exception:
                continue
        return concepts[:5]  # 最多返回 5 个概念
    except Exception:
        return []


def update_sector_cache(stock_codes: list[str], force: bool = False) -> dict:
    """
    更新行业缓存。返回 {code: {industry, sector, concepts, updated_at}}
    """
    cache = _load_cache()
    data = cache.get("data", {})
    now_iso = datetime.now().isoformat()

    for code in stock_codes:
        code = code.zfill(6)
        entry = data.get(code, {})
        ts = entry.get("updated_at")

        if not force and not _is_expired(ts) and entry.get("industry"):
            print(f"  ✓ {code} 缓存有效，跳过")
            continue

        print(f"  ⟳ 获取 {code} 行业/板块信息...")
        info = fetch_stock_info_akshare(code)
        if info:
            data[code] = {
                "code": code,
                "name": info.get("name", entry.get("name", "")),
                "industry": info.get("industry", ""),
                "sector": info.get("sector", ""),
                "concepts": entry.get("concepts", []),
                "updated_at": now_iso,
            }
            # 如果行业为空，尝试补充概念板块
            if not info.get("industry"):
                concepts = fetch_sector_concept_akshare(code)
                data[code]["concepts"] = concepts
            time.sleep(0.3)  # 避免请求过快
        else:
            # 保留旧数据，标记获取失败
            if code not in data:
                data[code] = {
                    "code": code,
                    "name": "",
                    "industry": "",
                    "sector": "",
                    "concepts": [],
                    "updated_at": now_iso,
                    "error": "fetch_failed",
                }

    cache["data"] = data
    cache["updated_at"] = now_iso
    _save_cache(cache)
    return data


def load_sector_cache() -> dict:
    """加载缓存，返回 {code: {industry, sector, ...}}"""
    cache = _load_cache()
    return cache.get("data", {})


def get_sector_for_codes(stock_codes: list[str], auto_fetch: bool = True) -> dict:
    """
    主入口：获取多只股票的行业/板块信息。
    优先读缓存，缓存过期或缺失时自动获取。

    返回：{code: {"industry": str, "sector": str, "concepts": list}}
    """
    cache = load_sector_cache()
    to_fetch = []

    for code in stock_codes:
        code = code.zfill(6)
        entry = cache.get(code, {})
        if not entry.get("industry") and not entry.get("sector"):
            to_fetch.append(code)

    if to_fetch and auto_fetch:
        print(f"[fetch_sector] 需要获取 {len(to_fetch)} 只股票行业信息: {to_fetch[:5]}...")
        update_sector_cache(to_fetch, force=False)
        cache = load_sector_cache()

    result = {}
    for code in stock_codes:
        code = code.zfill(6)
        entry = cache.get(code, {})
        result[code] = {
            "industry": entry.get("industry", ""),
            "sector": entry.get("sector", ""),
            "concepts": entry.get("concepts", []),
            "name": entry.get("name", ""),
        }
    return result


# ============================================================
# CLI
# ============================================================
def _collect_codes_from_config() -> list[str]:
    """从 config.yaml 收集所有需要查询的股票代码"""
    import yaml
    cfg_path = ROOT / "config.yaml"
    if not cfg_path.exists():
        return []
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    codes = set()
    # real_portfolio_rules
    for code in cfg.get("real_portfolio_rules", {}).keys():
        codes.add(code)
    # watchlist.user_manual
    for code in cfg.get("watchlist", {}).get("user_manual", {}).keys():
        codes.add(code)
    return sorted(codes)


def main():
    parser = argparse.ArgumentParser(description="获取A股股票行业/板块信息")
    parser.add_argument("codes", nargs="*", help="股票代码（如 600309 002709），不填则从 config.yaml 读取")
    parser.add_argument("--force", action="store_true", help="强制重新获取（忽略缓存）")
    parser.add_argument("--show", action="store_true", help="仅展示缓存内容")
    args = parser.parse_args()

    if args.show:
        data = load_sector_cache()
        print(f"\n📊 行业缓存（共 {len(data)} 条）：")
        for code, v in sorted(data.items()):
            ind = v.get("industry") or "❓"
            sec = v.get("sector") or "❓"
            print(f"  {code} {v.get('name', ''):<8s}  行业={ind}  板块={sec}")
        return

    codes = [c.zfill(6) for c in args.codes] if args.codes else _collect_codes_from_config()
    if not codes:
        print("❌ 没有指定股票代码，且 config.yaml 也没有找到持仓/观察池")
        sys.exit(1)

    print(f"\n📥 获取 {len(codes)} 只股票的行业/板块信息...")
    update_sector_cache(codes, force=args.force)

    print(f"\n✅ 完成！缓存保存在 {CACHE_FILE}")
    print(f"   运行 `python scripts/fetch_sector.py --show` 查看结果\n")


if __name__ == "__main__":
    main()
