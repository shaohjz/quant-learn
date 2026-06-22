#!/usr/bin/env python3
"""
盘中盯盘通知（定时运行）— 优化版，使用批量获取

功能：
  1. 从 config.yaml 读取 watchlist 和触发规则
  2. 批量获取实时行情数据（提高效率）
  3. 检查是否触发预设条件
  4. 如果发现触发，立即推送企微通知
  5. 避免重复通知（记录已通知的状态）

依赖：
  - config.yaml（watchlist 配置）
  - gateways/realtime_price_gateway.py（实时行情）
  - scripts/wecom_notifier.py（企微通知）
  - data/trigger_states.json（触发状态记录）
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.wecom_notifier import send_markdown
from gateways.realtime_price_gateway import RealtimePriceGateway


def load_watchlist_rules() -> Dict[str, Any]:
    """从 config.yaml 加载 watchlist 规则"""
    config_path = Path(__file__).parent.parent / "config.yaml"
    
    if not config_path.exists():
        print(f"❌ 错误：找不到配置文件 {config_path}")
        return {}
    
    try:
        import yaml
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return config.get('watchlist', {})
    except Exception as e:
        print(f"❌ 加载配置文件失败: {e}")
        return {}


def check_triggers() -> List[Dict[str, Any]]:
    """检查触发条件（优化版：批量获取行情）"""
    watchlist = load_watchlist_rules()
    triggers = []
    
    if not watchlist:
        return triggers
    
    # 收集所有需要监控的股票代码
    stock_codes = []
    stock_info_map = {}
    
    for stock_code, stock_info in watchlist.get('user_manual', {}).items():
        if not stock_info.get('enabled', True):
            continue
        
        stock_codes.append(stock_code)
        stock_info_map[stock_code] = stock_info
    
    if not stock_codes:
        return triggers
    
    print(f"⟳ 正在批量获取 {len(stock_codes)} 只股票的实时行情...")
    
    # 批量获取实时股价
    try:
        gateway = RealtimePriceGateway()
        prices = gateway.get_batch_prices(stock_codes)
        print(f"✅ 批量获取完成")
    except Exception as e:
        print(f"❌ 批量获取实时行情失败: {e}")
        return triggers
    
    # 遍历检查触发条件
    for stock_code, stock_info in stock_info_map.items():
        stock_name = stock_info.get('name', '未知')
        rules = stock_info.get('rules', {})
        
        if not rules:
            continue
        
        current_price = prices.get(stock_code)
        if current_price is None or current_price <= 0:
            print(f"⚠️ {stock_name}({stock_code}) 获取价格失败，跳过")
            continue
        
        # 检查每条规则
        for rule_name, rule_config in rules.items():
            trigger_price = rule_config.get('trigger', 0)
            direction = rule_config.get('dir', 'below')
            message = rule_config.get('msg', '')
            
            # 判断是否需要调整方向（默认是反向的，即低于触发价时买入，高于时卖出）
            if direction == 'below':
                triggered = current_price <= trigger_price
            else:  # above
                triggered = current_price >= trigger_price
            
            if triggered:
                triggers.append({
                    'code': stock_code,
                    'name': stock_name,
                    'rule': rule_name,
                    'trigger_price': trigger_price,
                    'current_price': current_price,
                    'direction': direction,
                    'message': message
                })
    
    return triggers


def format_trigger_notification(triggers: List[Dict[str, Any]], chunk_index: int = 0, total_chunks: int = 1) -> str:
    """格式化触发通知（支持分段）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    header = f"## ⚠️ 盘中触发 | {now}"
    if total_chunks > 1:
        header += f" (第{chunk_index+1}/{total_chunks}部分)"
    
    lines = [header + "\n"]
    
    for trigger in triggers:
        name = trigger.get('name', '未知')
        code = trigger.get('code', '000000')
        rule = trigger.get('rule', '')
        trigger_price = trigger.get('trigger_price', 0)
        current_price = trigger.get('current_price', 0)
        message = trigger.get('message', '')
        
        lines.append(f"**{name}**({code}) — 当前价 ¥{current_price:.2f}")
        lines.append(f"  > 触发条件: {rule} ({'≤' if trigger.get('direction') == 'below' else '≥'}¥{trigger_price:.2f})")
        if message:
            lines.append(f"  > {message}")
        lines.append("")  # 空行分隔
    
    return "\n".join(lines)


def split_triggers_to_chunks(triggers: List[Dict[str, Any]], max_length: int = 3500) -> List[List[Dict[str, Any]]]:
    """将触发列表按照字符长度限制分段"""
    chunks = []
    current_chunk = []
    current_length = 0
    
    # 预留标题和格式开销
    overhead = 200
    
    for trigger in triggers:
        # 估算这个 trigger 的字符长度
        trigger_text = format_trigger_notification([trigger])
        trigger_length = len(trigger_text)
        
        if current_length + trigger_length > max_length - overhead and current_chunk:
            # 当前 chunk 已满，保存并开始新 chunk
            chunks.append(current_chunk)
            current_chunk = [trigger]
            current_length = trigger_length
        else:
            current_chunk.append(trigger)
            current_length += trigger_length
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def load_notified_states() -> Dict[str, str]:
    """加载已通知状态"""
    states_file = Path(__file__).parent.parent / "data" / "trigger_states.json"
    if states_file.exists():
        try:
            with open(states_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_notified_states(states: Dict[str, str]):
    """保存已通知状态"""
    states_file = Path(__file__).parent.parent / "data" / "trigger_states.json"
    states_file.parent.mkdir(parents=True, exist_ok=True)
    with open(states_file, 'w', encoding='utf-8') as f:
        json.dump(states, f, ensure_ascii=False, indent=2)


def main():
    """主函数"""
    print(f"⟳ 盘中盯盘检查开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查触发条件
    triggers = check_triggers()
    
    if not triggers:
        print("✅ 无触发条件")
        return
    
    print(f"⚠️ 发现 {len(triggers)} 个触发条件")
    
    # 过滤已通知的（避免重复）
    states = load_notified_states()
    new_triggers = []
    
    for trigger in triggers:
        key = f"{trigger['code']}_{trigger['rule']}"
        last_notified = states.get(key)
        
        # 如果从未通知过，或者距离上次通知超过1小时，则再次通知
        if not last_notified:
            new_triggers.append(trigger)
            states[key] = datetime.now().isoformat()
        else:
            try:
                last_time = datetime.fromisoformat(last_notified)
                if (datetime.now() - last_time).total_seconds() > 3600:  # 1小时
                    new_triggers.append(trigger)
                    states[key] = datetime.now().isoformat()
            except ValueError:
                # 时间格式错误，重新通知
                new_triggers.append(trigger)
                states[key] = datetime.now().isoformat()
    
    if not new_triggers:
        print("✅ 无新触发（均已通知过）")
        return
    
    print(f"📤 准备发送 {len(new_triggers)} 个新触发通知")
    
    # 分段发送通知（避免超过4096字符限制）
    chunks = split_triggers_to_chunks(new_triggers)
    total_chunks = len(chunks)
    
    print(f"📤 将分 {total_chunks} 段发送通知")
    
    all_success = True
    for i, chunk in enumerate(chunks):
        notification = format_trigger_notification(chunk, chunk_index=i, total_chunks=total_chunks)
        
        print(f"📤 发送第 {i+1}/{total_chunks} 段 ({len(chunk)} 个触发)...")
        
        try:
            success = send_markdown(notification)
            if success:
                print(f"✅ 第 {i+1} 段发送成功")
            else:
                print(f"❌ 第 {i+1} 段发送失败")
                all_success = False
        except Exception as e:
            print(f"❌ 第 {i+1} 段发送异常: {e}")
            all_success = False
    
    if all_success:
        print(f"✅ 所有通知发送成功")
        
        # 保存状态
        save_notified_states(states)
        print(f"💾 触发状态已保存")
    else:
        print(f"❌ 部分通知发送失败")


if __name__ == "__main__":
    main()
