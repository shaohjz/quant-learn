#!/usr/bin/env python3
"""
盘中盯盘通知（定时运行）— 纯代码脚本

功能：
  1. 检查关注池中是否有股票触发预设条件
  2. 如果发现触发，立即推送通知
  3. 避免重复通知（记录已通知的状态）

数据源：
  - config.yaml（关注池 + 触发条件）
  - 实时行情接口（需要集成）
  - data/trigger_states.json（记录已通知状态）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.wecom_notifier import send_markdown


def check_triggers() -> list:
    """检查触发条件（示例实现）"""
    # TODO: 实际应该：
    # 1. 读取 config.yaml 中的 watchlist 和 rules
    # 2. 获取实时行情
    # 3. 检查是否触发条件
    # 4. 返回触发的列表
    
    # 示例：返回空列表（无触发）
    return []


def format_trigger_notification(triggers: list) -> str:
    """格式化触发通知"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    lines = [
        f"## ⚠️ 盘中触发 | {now}\n"
    ]
    
    for trigger in triggers:
        name = trigger.get("name", "未知")
        code = trigger.get("code", "000000")
        rule = trigger.get("rule", "")
        price = trigger.get("price", 0)
        
        lines.append(f"**{name}**({code}) — ¥{price:.2f}")
        lines.append(f"  > {rule}")
    
    return "\n".join(lines)


def load_notified_states() -> dict:
    """加载已通知状态"""
    states_file = Path(__file__).parent.parent / "data" / "trigger_states.json"
    if states_file.exists():
        with open(states_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_notified_states(states: dict):
    """保存已通知状态"""
    states_file = Path(__file__).parent.parent / "data" / "trigger_states.json"
    states_file.parent.mkdir(parents=True, exist_ok=True)
    with open(states_file, 'w', encoding='utf-8') as f:
        json.dump(states, f, ensure_ascii=False, indent=2)


def main():
    """主函数"""
    # 检查触发条件
    triggers = check_triggers()
    
    if not triggers:
        # 没有触发，不发送通知
        print("✅ 无触发条件")
        return
    
    # 过滤已通知的（避免重复）
    states = load_notified_states()
    new_triggers = []
    
    for trigger in triggers:
        key = f"{trigger['code']}_{trigger['rule']}"
        if key not in states or (datetime.now() - datetime.fromisoformat(states[key])).total_seconds() > 3600:
            # 超过1小时可以再次通知
            new_triggers.append(trigger)
            states[key] = datetime.now().isoformat()
    
    if not new_triggers:
        print("✅ 无新触发")
        return
    
    # 发送通知
    notification = format_trigger_notification(new_triggers)
    send_markdown(notification)
    
    # 保存状态
    save_notified_states(states)


if __name__ == "__main__":
    main()
