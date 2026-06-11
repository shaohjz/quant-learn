"""Patch: daily_advisor 推送时写入 push_history"""
from pathlib import Path

f = Path('scripts/daily_advisor.py')
text = f.read_text(encoding='utf-8')

# 在 push_webhook 函数后面加一个 save_push_history
old = '''def push_webhook(content: str):
    url = load_webhook()
    if not url:
        logger.warning("未配置 webhook")
        return False
    body = json.dumps({"msgtype": "text", "text": {"content": content}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        logger.error(f"推送失败: {e}")
        return False'''

new = '''def push_webhook(content: str):
    url = load_webhook()
    if not url:
        logger.warning("未配置 webhook")
        return False
    body = json.dumps({"msgtype": "text", "text": {"content": content}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        logger.error(f"推送失败: {e}")
        return False


def save_push_history(phase: str, content: str, push_type: str = 'advisor'):
    """保存推送记录到数据库"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO push_history (push_type, phase, content) VALUES (?,?,?)",
            (f"{push_type}_{phase}", phase, content)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass'''

text = text.replace(old, new)

# 在 main 的推送逻辑里加入 save
old_main = '''    if not args.no_webhook:
        if push_webhook(content):
            logger.info("✓ 已推送企微")'''

new_main = '''    # 保存推送历史
    save_push_history(phase, content)
    
    if not args.no_webhook:
        if push_webhook(content):
            logger.info("✓ 已推送企微")'''

text = text.replace(old_main, new_main)

f.write_text(text, encoding='utf-8')
print("✓ daily_advisor patched")
