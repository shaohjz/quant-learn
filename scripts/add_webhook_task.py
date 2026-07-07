#!/usr/bin/env python3
"""添加Webhook配置任务"""
import sqlite3
from datetime import datetime

def add_task():
    # 连接PM数据库
    conn = sqlite3.connect('data/pm.db')
    cursor = conn.cursor()
    
    # 检查是否已有类似任务
    cursor.execute("""
        SELECT id, title, status 
        FROM tasks 
        WHERE title LIKE '%Webhook%' OR title LIKE '%企微%' 
        ORDER BY id DESC 
        LIMIT 1
    """)
    existing = cursor.fetchone()
    
    if existing:
        print(f"发现已有相关任务: {existing[0]} - {existing[1]} ({existing[2]})")
        print("如需添加新任务，请先关闭或删除旧任务")
        conn.close()
        return
    
    # 检查当前最大ID
    cursor.execute('SELECT id FROM tasks ORDER BY id DESC LIMIT 1')
    last_id = cursor.fetchone()
    if last_id:
        num = int(last_id[0].split('-')[1])
        new_id = f'REQ-{num + 1:03d}'
    else:
        new_id = 'REQ-001'
    
    print(f'新任务ID: {new_id}')
    
    # 任务描述
    description = """## 问题描述
理财师每日复盘报告无法自动推送到企微群。

## 原因
`config.yaml` 中的 `wecom_webhook` 配置为空字符串：
```yaml
wecom_webhook: ''  # 请在企微群里添加自定义机器人，获取 Webhook URL 并替换此处
```

## 影响
1. 每日复盘报告只能通过文件查看，无法自动通知
2. 理财师Agent的定时任务（cron）无法完成推送步骤
3. 需要手动检查报告文件

## 解决方案
1. 在企微群里添加自定义机器人
2. 获取Webhook URL（格式: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...）
3. 将URL配置到以下任一位置：
   - 环境变量: `WECOM_WEBHOOK_URL`
   - 配置文件: `config.local.yaml` 或 `config.yaml` 的 `notifier.wecom_webhook` 字段

## 验证方法
配置完成后，运行：
```bash
python -c "from scripts.wecom_webhook import get_webhook_url; print(get_webhook_url())"
```
应该输出Webhook URL（前50个字符）。

## 优先级
P1 - 重要但不紧急，影响自动化流程
"""
    
    # 添加任务
    task_data = (
        new_id,
        'story',
        '配置企微Webhook URL - 启用自动推送',
        description,
        'open',
        'P1',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    cursor.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, task_data)
    
    conn.commit()
    conn.close()
    
    print(f"✅ 已添加任务: {new_id}")
    print(f"标题: 配置企微Webhook URL - 启用自动推送")
    print(f"优先级: P1")
    print(f"状态: open")
    print(f"\n请通过PM系统查看完整描述")

if __name__ == '__main__':
    add_task()
