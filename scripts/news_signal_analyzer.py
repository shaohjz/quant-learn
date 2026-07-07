#!/usr/bin/env python3
"""
新闻信号分析器 - 分析今日新闻信号并判断利好/利空/中性
"""
import json
import sqlite3
from datetime import datetime

# 读取今日新闻信号
with open('output/news_signals_2026-07-05.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

signals = data['signals']
print(f"📊 共读取 {len(signals)} 条新闻信号")

# 连接数据库
conn = sqlite3.connect('data/sim_live_mirror.db')
c = conn.cursor()

# 统计
buy_count = 0
sell_count = 0
hold_count = 0
updated_count = 0
failed_count = 0

# 分析每条信号
for signal in signals:
    signal_id = signal['id']
    title = signal['title']
    stock_code = signal['stock_code']
    stock_name = signal['stock_name']
    
    # 初始化
    signal_action = 'HOLD'
    confidence = 0.5
    signal_reason = '无明显利好利空'
    
    # 关键词匹配规则
    title_lower = title.lower()
    
    # 利好关键词
    buy_keywords = [
        '回购', '增持', '分红', '派息', '业绩增长', '预增', '扭亏',
        '订单', '合同', '中标', '收购', '并购', '重组', '股权激励',
        '涨停', '历史新高', '突破', '流入', '净流入', '机构买入',
        '获得批准', '获批', '认证', '合作', '战略', '创新高'
    ]
    
    # 利空关键词
    sell_keywords = [
        '减持', '平仓', '质押', '冻结', '业绩下滑', '预减', '亏损',
        '诉讼', '仲裁', '处罚', '违规', '调查', '风险', '警示',
        '跌停', '下跌', '流出', '净流出', '主力出逃', '机构卖出',
        '退市', 'ST', '*ST', '停产', '断供', '违约', '冻结'
    ]
    
    # 检查利好
    for kw in buy_keywords:
        if kw in title:
            signal_action = 'BUY'
            confidence = 0.75
            signal_reason = f'利好：{kw}相关正面消息'
            buy_count += 1
            break
    
    # 如果还没判断为利好，检查利空
    if signal_action == 'HOLD':
        for kw in sell_keywords:
            if kw in title:
                signal_action = 'SELL'
                confidence = 0.75
                signal_reason = f'利空：{kw}相关负面消息'
                sell_count += 1
                break
    
    # 如果还是中性
    if signal_action == 'HOLD':
        hold_count += 1
        # 检查一些中性但偏正面的词汇
        neutral_positive = ['涨', '拉升', '走强', '活跃', '放量']
        neutral_negative = ['震荡', '调整', '回落', '盘整']
        
        for kw in neutral_positive:
            if kw in title:
                signal_action = 'BUY'
                confidence = 0.6
                signal_reason = f'中性偏多：{kw}'
                buy_count += 1
                hold_count -= 1
                break
        
        if signal_action == 'HOLD':
            for kw in neutral_negative:
                if kw in title:
                    signal_action = 'SELL'
                    confidence = 0.6
                    signal_reason = f'中性偏空：{kw}'
                    sell_count += 1
                    hold_count -= 1
                    break
    
    # 更新数据库
    try:
        c.execute(
            'UPDATE strategy_shadow_signals SET signal_action=?, confidence=?, signal_reason=? WHERE id=?',
            (signal_action, confidence, signal_reason, signal_id)
        )
        updated_count += 1
        
        if updated_count % 50 == 0:
            print(f"  处理进度: {updated_count}/{len(signals)}")
            
    except Exception as e:
        print(f"❌ 更新失败 ID={signal_id}: {e}")
        failed_count += 1

# 提交事务
conn.commit()
conn.close()

print(f"\n✅ 分析完成！")
print(f"📈 利好(BUY): {buy_count} 条")
print(f"📉 利空(SELL): {sell_count} 条")
print(f"⚪ 中性(HOLD): {hold_count} 条")
print(f"✅ 成功更新: {updated_count} 条")
print(f"❌ 更新失败: {failed_count} 条")

# 输出汇总消息
summary = f"📰 今日新闻信号分析完成：{buy_count}条利好，{sell_count}条利空，{hold_count}条中性"
print(f"\n{summary}")
print(summary, file=open('output/news_analysis_summary.txt', 'w', encoding='utf-8'))
