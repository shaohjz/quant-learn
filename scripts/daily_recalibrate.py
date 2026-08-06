"""
scripts/daily_recalibrate.py — 每日盘前阈值自动校准

逻辑：
  1. 用 BaoStock 拉每只股票最近 60 日日线（前复权）
  2. 计算 MA5 / MA10 / MA20 / ATR14
  3. 按规则更新 config.yaml 里的阈值：
     观察股：
       buy_zone   = MA10（短期支撑）
       buy_strong = MA20（中期趋势支撑）
       trend_break = MA20 - 1.5×ATR（破位确认）
     持仓股（real_portfolio_rules）：
       stop_loss / trend_break = MA20 × 0.97（MA20 下方 3% 止损缓冲）
       take_profit = max(买入成本 × 1.15, MA20 + 2×ATR)
  4. 直接修改 config.yaml（精准文本替换，保持格式和注释）
  5. 打印对比表：旧阈值 → 新阈值
  6. 如果某只股票数据不够（< 20 天），跳过

BaoStock 注意事项：
  - 代码格式：sh.600186 / sz.002290
  - adjustflag='2' = 前复权
  - 停牌日返回空字符串，需 pd.to_numeric + dropna
  - 需要 bs.login() / bs.logout()
"""

import sys, re
from pathlib import Path
from datetime import date, timedelta

# Windows GBK 编码兼容：允许 print 输出 emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
import baostock as bs
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIG_FILE = ROOT / "config.yaml"
CONFIG_AUTO_FILE = ROOT / "config_auto.yaml"


# ============================================================
# BaoStock 数据拉取
# ============================================================

def code_to_baostock(code: str) -> str:
    """A股代码 → BaoStock 格式 (sh.XXXXXX / sz.XXXXXX)"""
    code = code.strip()
    if code.startswith(("6", "5", "9", "11")):
        return f"sh.{code}"
    else:
        return f"sz.{code}"


def fetch_klines_baostock(code: str, days: int = 90) -> pd.DataFrame | None:
    """用 BaoStock 拉取最近 N 天日线（前复权），返回 DataFrame 或 None"""
    bs_code = code_to_baostock(code)
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",  # 前复权
    )

    if rs.error_code != "0":
        print(f"  ❌ BaoStock 查询失败 {bs_code}: {rs.error_msg}")
        return None

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=rs.fields)
    # 转数值（停牌日为空字符串）
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])
    df = df.reset_index(drop=True)
    return df


# ============================================================
# 技术指标计算
# ============================================================

def calc_indicators(df: pd.DataFrame) -> dict | None:
    """计算 MA5/MA10/MA20/ATR14，返回最新值 dict 或 None"""
    if len(df) < 20:
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    ma5 = float(np.mean(close[-5:]))
    ma10 = float(np.mean(close[-10:]))
    ma20 = float(np.mean(close[-20:]))

    # ATR14: True Range 的 14 日均值
    if len(df) < 15:
        atr14 = float(np.mean(high[-14:] - low[-14:]))  # 简化
    else:
        tr_list = []
        for i in range(1, min(15, len(df))):
            idx = len(df) - 15 + i
            if idx < 1:
                continue
            h = high[idx]
            l = low[idx]
            prev_c = close[idx - 1]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)
        atr14 = float(np.mean(tr_list)) if tr_list else 0.0

    # 取最后一条数据日期（BaoStock 格式）
    last_date = str(df["date"].iloc[-1]) if "date" in df.columns else "N/A"
    return {
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "atr14": round(atr14, 2),
        "last_close": round(float(close[-1]), 2),
        "trade_date": last_date,
    }


# ============================================================
# 阈值计算规则
# ============================================================

def calc_watchlist_thresholds(ind: dict) -> dict:
    """观察股阈值计算"""
    ma10 = ind["ma10"]
    ma20 = ind["ma20"]
    atr = ind["atr14"]
    return {
        "buy_zone": round(ma10, 2),
        "buy_strong": round(ma20, 2),
        "trend_break": round(ma20 - 1.5 * atr, 2),
    }


def calc_portfolio_thresholds(ind: dict, avg_cost: float | None = None) -> dict:
    """持仓股阈值计算"""
    ma20 = ind["ma20"]
    atr = ind["atr14"]

    stop_loss = round(ma20 * 0.97, 2)
    
    # take_profit: max(成本×1.15, MA20 + 2×ATR)
    tp_ma = ma20 + 2 * atr
    if avg_cost and avg_cost > 0:
        tp_cost = avg_cost * 1.15
        take_profit = round(max(tp_cost, tp_ma), 2)
    else:
        take_profit = round(tp_ma, 2)

    return {
        "stop_loss": stop_loss,
        "trend_break": stop_loss,  # 同义
        "take_profit": take_profit,
    }


# ============================================================
# 精准文本替换（保持 YAML 格式）
# ============================================================

def replace_trigger_in_text(text: str, section_code: str, rule_name: str,
                            old_trigger: float, new_trigger: float,
                            new_msg: str | None = None) -> str:
    """
    在 config.yaml 文本中，精准替换指定股票指定规则的 trigger 和 msg。
    使用正则找到对应行并替换。
    """
    # 构建 trigger 替换：找到 rule_name 对应行的 trigger 值
    # 格式: rule_name: { trigger: XX.XX, dir: ..., msg: "..." }
    # 或者 rule_name:    { trigger: XX.XX, dir: ..., msg: "..." }
    
    # 将 old_trigger 格式化为可能的字符串形式
    old_strs = set()
    old_strs.add(f"{old_trigger:.2f}")
    old_strs.add(f"{old_trigger:.1f}")
    old_strs.add(f"{old_trigger:g}")
    if old_trigger == int(old_trigger):
        old_strs.add(f"{int(old_trigger)}.0")
        old_strs.add(f"{int(old_trigger)}.00")

    new_trigger_str = f"{new_trigger:.2f}"

    # 逐行查找并替换
    lines = text.split("\n")
    in_target_code = False
    found = False

    for i, line in enumerate(lines):
        # 检测是否进入目标代码块（通过缩进和代码标识）
        # 观察股格式: "  \"002290\":" 或 "  \"600186\":"
        # 持仓股格式: "  \"600330\":"
        stripped = line.strip()
        if stripped.startswith(f'"{section_code}"') and stripped.endswith(":"):
            in_target_code = True
            continue

        # 检测是否离开目标代码块（遇到同级缩进的另一个代码）
        if in_target_code and stripped and not stripped.startswith("#"):
            # 检查是否是另一个股票代码（同级缩进）
            if re.match(r'^"\d{6}":', stripped):
                in_target_code = False
                continue

        if in_target_code and rule_name in line and "trigger:" in line:
            # 找到目标行，用正则替换 trigger 后的整个数字
            new_line = re.sub(
                r'trigger:\s*[\d.]+',
                f'trigger: {new_trigger_str}',
                lines[i],
                count=1
            )
            if new_line != lines[i]:
                lines[i] = new_line
                found = True
            
            # 替换 msg
            if new_msg and found:
                # msg 在同一行：msg: "..."
                msg_pattern = r'msg:\s*"[^"]*"'
                escaped_msg = new_msg.replace("\\", "\\\\")
                replacement = f'msg: "{escaped_msg}"'
                lines[i] = re.sub(msg_pattern, replacement, lines[i])
            
            if found:
                break

    if not found:
        # Fallback: 更宽松的搜索（不限制在代码块内）
        for i, line in enumerate(lines):
            if rule_name in line and "trigger:" in line:
                # 回溯找代码
                for j in range(i - 1, max(i - 15, -1), -1):
                    if f'"{section_code}"' in lines[j]:
                        lines[i] = re.sub(
                            r'trigger:\s*[\d.]+',
                            f'trigger: {new_trigger_str}',
                            lines[i],
                            count=1
                        )
                        if new_msg:
                            msg_pattern = r'msg:\s*"[^"]*"'
                            escaped_msg = new_msg.replace("\\", "\\\\")
                            replacement = f'msg: "{escaped_msg}"'
                            lines[i] = re.sub(msg_pattern, replacement, lines[i])
                        found = True
                        break
                if found:
                    break
                if found:
                    break

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def get_avg_cost_from_db(code: str) -> float | None:
    """从模拟盘 DB 获取真实账户(account_id=2)的买入均价"""
    try:
        import sqlite3
        from sim.config_resolver import resolve_db_path
        db_path = resolve_db_path()
        if not db_path.exists():
            return None
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT avg_cost FROM sim_positions WHERE account_id=2 AND stock_code=? AND quantity>0",
            (code,)
        ).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def collect_calibration_codes(
    watchlist: dict,
    portfolio_rules: dict | None = None,
    auto_discovered: dict | None = None,
) -> dict[str, dict]:
    """收集待校准股票（REQ-105：展开嵌套 user_manual / auto_discovered）。

    返回 {code: {type, name, body, config_file}}。
    config_file: 'config' | 'auto'
    """
    all_codes: dict[str, dict] = {}
    watchlist = watchlist or {}
    portfolio_rules = portfolio_rules or {}
    auto_discovered = auto_discovered or {}

    is_nested = "user_manual" in watchlist or "auto_discovered" in watchlist
    if is_nested:
        for code, body in (watchlist.get("user_manual") or {}).items():
            if isinstance(body, dict) and body.get("enabled", True):
                all_codes[str(code)] = {
                    "type": "watchlist",
                    "name": body.get("name", ""),
                    "body": body,
                    "config_file": "config",
                }
        for code, body in auto_discovered.items():
            if isinstance(body, dict) and body.get("enabled", True):
                all_codes[str(code)] = {
                    "type": "watchlist",
                    "name": body.get("name", ""),
                    "body": body,
                    "config_file": "auto",
                }
        for code, body in (watchlist.get("auto_discovered") or {}).items():
            if (
                isinstance(body, dict)
                and body.get("enabled", True)
                and str(code) not in all_codes
            ):
                all_codes[str(code)] = {
                    "type": "watchlist",
                    "name": body.get("name", ""),
                    "body": body,
                    "config_file": "config",
                }
    else:
        for code, body in watchlist.items():
            if isinstance(body, dict) and body.get("enabled", True):
                all_codes[str(code)] = {
                    "type": "watchlist",
                    "name": body.get("name", ""),
                    "body": body,
                    "config_file": "config",
                }

    for code, body in portfolio_rules.items():
        if not isinstance(body, dict):
            continue
        all_codes[str(code)] = {
            "type": "portfolio",
            "name": body.get("name", ""),
            "body": body,
            "config_file": "config",
        }
    return all_codes


def main():
    print("=" * 60)
    print("📊 每日盘前阈值自动校准 (BaoStock)")
    print("=" * 60)

    # 登录 BaoStock
    lg = bs.login()
    if lg.error_code != "0":
        print(f"❌ BaoStock 登录失败: {lg.error_msg}")
        return 1
    print(f"✅ BaoStock 登录成功\n")

    try:
        # 读取 config.yaml
        config_text = CONFIG_FILE.read_text(encoding="utf-8")
        cfg = yaml.safe_load(config_text)

        watchlist = cfg.get("watchlist", {}) or {}
        portfolio_rules = cfg.get("real_portfolio_rules", {}) or {}

        auto_text = ""
        auto_cfg: dict = {}
        if CONFIG_AUTO_FILE.exists():
            auto_text = CONFIG_AUTO_FILE.read_text(encoding="utf-8")
            auto_cfg = yaml.safe_load(auto_text) or {}

        all_codes = collect_calibration_codes(
            watchlist,
            portfolio_rules,
            auto_discovered=auto_cfg.get("auto_discovered") or {},
        )

        print(f"共 {len(all_codes)} 只股票需要校准\n")

        # 对比表
        changes = []
        skipped = []

        def _apply_replace(target: str, code: str, rule_name: str,
                           old_val: float, new_val: float, new_msg: str) -> None:
            """按股票所在文件写回 trigger。"""
            nonlocal config_text, auto_text
            if target == "auto":
                auto_text = replace_trigger_in_text(
                    auto_text, code, rule_name, old_val, new_val, new_msg
                )
            else:
                config_text = replace_trigger_in_text(
                    config_text, code, rule_name, old_val, new_val, new_msg
                )

        for code, info in all_codes.items():
            name = info["name"]
            stype = info["type"]
            cfg_target = info.get("config_file", "config")
            print(f"  📈 {code} {name} ({stype})...", end=" ")

            # 拉取日线
            df = fetch_klines_baostock(code)
            if df is None or len(df) < 20:
                print(f"⚠️ 数据不足 ({len(df) if df is not None else 0} 天), 跳过")
                skipped.append(f"{code} {name}")
                continue

            # 计算指标
            ind = calc_indicators(df)
            if ind is None:
                print("⚠️ 指标计算失败, 跳过")
                skipped.append(f"{code} {name}")
                continue

            print(f"MA10={ind['ma10']} MA20={ind['ma20']} ATR={ind['atr14']}")

            rules = info["body"].get("rules", {})
            if not isinstance(rules, dict):
                print("⚠️ rules 非 dict, 跳过")
                skipped.append(f"{code} {name}")
                continue

            if stype == "watchlist":
                new_thresh = calc_watchlist_thresholds(ind)

                # 更新 buy_zone
                if "buy_zone" in rules:
                    old_val = float(rules["buy_zone"].get("trigger", 0))
                    new_val = new_thresh["buy_zone"]
                    if old_val != new_val:
                        new_msg = f"💰 {name} BuyZone 阈值 {new_val}（{ind['trade_date']} MA10={ind['ma10']}），试探建仓"
                        _apply_replace(cfg_target, code, "buy_zone", old_val, new_val, new_msg)
                        changes.append(f"  {code} {name} buy_zone: {old_val} → {new_val}")

                # 更新 buy_strong
                if "buy_strong" in rules:
                    old_val = float(rules["buy_strong"].get("trigger", 0))
                    new_val = new_thresh["buy_strong"]
                    if old_val != new_val:
                        new_msg = f"💰💰 {name} BuyStrong 阈值 {new_val}（{ind['trade_date']} MA20={ind['ma20']}），优质建仓区"
                        _apply_replace(cfg_target, code, "buy_strong", old_val, new_val, new_msg)
                        changes.append(f"  {code} {name} buy_strong: {old_val} → {new_val}")

                # 更新 trend_break
                if "trend_break" in rules:
                    old_val = float(rules["trend_break"].get("trigger", 0))
                    new_val = new_thresh["trend_break"]
                    if old_val != new_val:
                        new_msg = f"⚠️ {name}破 {new_val}！跌破 MA20-1.5ATR，趋势可能反转"
                        _apply_replace(cfg_target, code, "trend_break", old_val, new_val, new_msg)
                        changes.append(f"  {code} {name} trend_break: {old_val} → {new_val}")

            elif stype == "portfolio":
                avg_cost = get_avg_cost_from_db(code)
                new_thresh = calc_portfolio_thresholds(ind, avg_cost)

                # 更新 stop_loss
                if "stop_loss" in rules:
                    old_val = float(rules["stop_loss"].get("trigger", 0))
                    new_val = new_thresh["stop_loss"]
                    if old_val != new_val:
                        new_msg = f"🚨 {name}跌破 MA20×0.97 ({new_val})！止损线"
                        _apply_replace(cfg_target, code, "stop_loss", old_val, new_val, new_msg)
                        changes.append(f"  {code} {name} stop_loss: {old_val} → {new_val}")

                # 更新 stop_loss_tight (如果有)
                if "stop_loss_tight" in rules:
                    old_val = float(rules["stop_loss_tight"].get("trigger", 0))
                    new_val = round(ind["ma20"] * 0.98, 2)  # tighter: MA20 × 0.98
                    if old_val != new_val:
                        new_msg = f"⚠️ {name}跌破 MA20×0.98 ({new_val})！接近止损线"
                        _apply_replace(cfg_target, code, "stop_loss_tight", old_val, new_val, new_msg)
                        changes.append(f"  {code} {name} stop_loss_tight: {old_val} → {new_val}")

                # 更新 take_profit
                if "take_profit" in rules:
                    old_val = float(rules["take_profit"].get("trigger", 0))
                    new_val = new_thresh["take_profit"]
                    if old_val != new_val:
                        cost_str = f"(成本×1.15 或 MA20+2ATR)" if avg_cost else "(MA20+2ATR)"
                        new_msg = f"🎉 {name}涨至 {new_val}！{cost_str}，建议止盈"
                        _apply_replace(cfg_target, code, "take_profit", old_val, new_val, new_msg)
                        changes.append(f"  {code} {name} take_profit: {old_val} → {new_val}")

        # 写回 config.yaml / config_auto.yaml
        CONFIG_FILE.write_text(config_text, encoding="utf-8")
        if auto_text:
            CONFIG_AUTO_FILE.write_text(auto_text, encoding="utf-8")

        # 打印对比表
        print("\n" + "=" * 60)
        print("📋 校准结果汇总")
        print("=" * 60)

        if changes:
            print(f"\n✅ 已更新 {len(changes)} 个阈值:")
            for c in changes:
                print(c)
        else:
            print("\n✅ 所有阈值均为最新，无需更新")

        if skipped:
            print(f"\n⚠️ 跳过 {len(skipped)} 只（数据不足）:")
            for s in skipped:
                print(f"  {s}")

        print("\n✅ config.yaml 已更新完毕")
        if auto_text:
            print("✅ config_auto.yaml 已更新完毕")
        
        # ============================================================
        # 5/27 新增：阈值校准后紧接着重算 trend_filter（MA60 + MACD 趋势闸）
        # ============================================================
        try:
            print("\n" + "=" * 60)
            print("🔄 趋势过滤闸重算 (trend_filter)")
            print("=" * 60)
            import subprocess
            scripts_dir = Path(__file__).parent
            r1 = subprocess.run(
                [sys.executable, str(scripts_dir / 'trend_health_check.py')],
                cwd=str(scripts_dir.parent), capture_output=True, text=True, encoding='utf-8'
            )
            if r1.returncode == 0:
                print("✅ trend_health_check 完成")
                r2 = subprocess.run(
                    [sys.executable, str(scripts_dir / 'apply_trend_filter.py')],
                    cwd=str(scripts_dir.parent), capture_output=True, text=True, encoding='utf-8'
                )
                if r2.returncode == 0:
                    print("✅ apply_trend_filter 完成")
                    # 只打印最后的汇总部分
                    if r2.stdout:
                        for line in r2.stdout.splitlines()[-25:]:
                            print(line)
                else:
                    print(f"⚠️ apply_trend_filter 失败: {r2.stderr[:300]}")
            else:
                print(f"⚠️ trend_health_check 失败: {r1.stderr[:300]}")
        except Exception as ex:
            print(f"⚠️ trend_filter 重算异常（不影响阈值校准）: {ex}")
        
        return 0

    finally:
        bs.logout()
        print("\n🔒 BaoStock 已登出")


if __name__ == "__main__":
    sys.exit(main() or 0)


# ============================================================
# 注册 Windows 计划任务（每个交易日 8:25 跑）：
#
# schtasks /create /tn "QuantLearn_DailyRecalibrate" ^
#   /tr "C:\Users\Administrator\.openclaw\workspace\quant-learn\.venv\Scripts\python.exe C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\daily_recalibrate.py" ^
#   /sc weekly /d MON,TUE,WED,THU,FRI /st 08:25
#
# 查看：schtasks /query /tn "QuantLearn_DailyRecalibrate"
# 删除：schtasks /delete /tn "QuantLearn_DailyRecalibrate" /f
# ============================================================
