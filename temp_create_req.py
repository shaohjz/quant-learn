#!/usr/bin/env python3
"""临时脚本：直接调用 pm_cli 功能创建需求"""

import sys
import os

# 添加 scripts 目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

# 直接导入 pm_cli 模块并调用相关函数
from pm_cli import PMDatabase, main

# 测试：创建一个新的 Story 需求
db = PMDatabase('data/pm.db')

# 需求1：持仓基本面仪表板
req1 = db.create_requirement(
    type='story',
    title='持仓股票基本面仪表板 - 自动获取PE/PB/ROE指标',
    description='''当前持仓只有技术面和浮盈数据，缺少基本面指标。
自动从财经API获取持仓股票的：
- 估值指标：PE/PB/PS/PCF
- 盈利指标：ROE/ROA/毛利率/净利率
- 成长性：营收增长率/净利润增长率
- 财务健康：资产负债率/流动比率

在每日复盘报告中展示，辅助投资决策。''',
    priority='P1',
    owner='quant-agent'
)

print(f"✅ 已创建需求: {req1['id']} - {req1['title']}")

# 需求2：资金利用率监控与建议
req2 = db.create_requirement(
    type='story',
    title='资金利用率监控与优化建议',
    description='''当前 sim 账户现金只占比 5.37%（5,373/100,000），资金利用率低。
功能需求：
1. 实时监控账户现金占比，低于10%时告警
2. 根据市场环境（牛市/熊市/震荡）给出仓位建议
3. 自动计算最优仓位配置（单票仓位上限、行业分散度）
4. 在每日复盘报告中展示资金利用率指标''',
    priority='P1',
    owner='quant-agent'
)

print(f"✅ 已创建需求: {req2['id']} - {req2['title']}")

# 需求3：交易信号质量回溯测试
req3 = db.create_requirement(
    type='story',
    title='交易信号质量回溯测试 - buy_zone vs buy_strong 胜率分析',
    description='''当前系统有 buy_zone 和 buy_strong 两种买入信号，但缺少质量评估。
功能需求：
1. 回溯测试过去3个月的所有信号，计算：
   - 信号触发后N日收益率（1日/3日/5日/10日）
   - 胜率（盈利占比）
   - 平均盈利/亏损比
   - 最大回撤
2. 按信号类型（buy_zone vs buy_strong）分类统计
3. 按行业/板块分类统计
4. 生成信号质量报告，指导策略优化''',
    priority='P2',
    owner='quant-agent'
)

print(f"✅ 已创建需求: {req3['id']} - {req3['title']}")

# 需求4：自动化周度投资总结
req4 = db.create_requirement(
    type='story',
    title='自动化周度投资总结报告',
    description='''当前只有每日复盘，缺少周度维度的投资总结。
功能需求：
1. 每周五收盘后自动生成周度总结报告，包含：
   - 本周收益率 vs 大盘（沪深300/中证500）
   - 本周交易次数、胜率、盈亏比
   - 本周最佳/最差持仓
   - 本周策略信号质量评估
   - 下周市场展望与关注池
2. 推送到企微群
3. 存档到 docs/weekly_reviews/''',
    priority='P2',
    owner='quant-agent'
)

print(f"✅ 已创建需求: {req4['id']} - {req4['title']}")

# Bug报告：信号文本截断问题（加强版）
bug1 = db.create_requirement(
    type='bug',
    title='成交记录中信号文本被截断导致信息丢失',
    description='''2026-05-26 复盘报告中发现多处信号文本被截断：
- "💰 天赐材料跌至  " (应为 "💰 天赐材料跌至 buy zone")
- "💰💰 天赐材料" (信息不完整)
- "002709." (明显截断)

根因分析：
1. 数据库字段长度限制？
2. 写入时的字符串截断？
3. 读取时的格式化问题？

影响：无法追溯完整的买入理由，影响复盘分析。''',
    priority='S1',
    owner='quant-agent'
)

print(f"✅ 已创建Bug报告: {bug1['id']} - {bug1['title']}")

print("\n✅ 所有需求创建完成！")
