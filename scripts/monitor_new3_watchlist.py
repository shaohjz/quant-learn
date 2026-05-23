"""
新加入的 3 只观察股临时监控（不影响主 vqlearn 进程）
盯到 15:00 收盘自动退出
"""
import sys, time, requests, logging
from datetime import datetime, time as dtime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim.config import load_config

logger = logging.getLogger('new3')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

WATCH = [
    ('000725', 'sz', '京东方A', 4.80, 4.50),
    ('600309', 'sh', '万华化学', 76.00, 73.00),
    ('601728', 'sh', '中国电信', 6.10, 5.96),
]
FIRED = {}  # (code, level) -> True


def push(content):
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.info(f'[告警] {content}')
        return
    try:
        requests.post(webhook, json={'msgtype': 'markdown', 'markdown': {'content': content}}, timeout=5)
    except Exception as e:
        logger.warning(f'推送异常: {e}')


def fetch():
    list_str = ','.join(f'{prefix}{code}' for code, prefix, _, _, _ in WATCH)
    r = requests.get(f'https://hq.sinajs.cn/list={list_str}',
                     headers={'Referer': 'https://finance.sina.com.cn'}, timeout=5)
    quotes = {}
    for line in r.text.strip().split('\n'):
        if '=' not in line:
            continue
        sym = line.split('=')[0].split('_')[-1]
        parts = line.split('=')[1].strip(';\n').strip('"').split(',')
        code = sym[2:]
        quotes[code] = {
            'pre': float(parts[2]),
            'cur': float(parts[3]),
            'name': parts[0],
        }
    return quotes


def main():
    push(
        "## 🆕 涛哥推荐 3 只观察启用\n"
        "- 京东方A 000725 buy_zone 4.80 / strong 4.50\n"
        "- 万华化学 600309 buy_zone 76 / strong 73\n"
        "- 中国电信 601728 buy_zone 6.10 / strong 5.96\n\n"
        "📊 已加入 watchlist（来源: 涛哥推荐），明日 9:25 自动接入 vqlearn"
    )

    while True:
        now = datetime.now()
        if now.time() >= dtime(15, 0):
            logger.info('15:00 到点退出')
            break
        if now.weekday() >= 5:
            break
        if dtime(11, 30) <= now.time() < dtime(13, 0):
            time.sleep(60)
            continue

        try:
            quotes = fetch()
        except Exception as e:
            logger.warning(f'拉取异常: {e}')
            time.sleep(30)
            continue

        for code, prefix, name, bz, bs in WATCH:
            q = quotes.get(code)
            if not q:
                continue
            cur = q['cur']
            chg = (cur / q['pre'] - 1) * 100 if q['pre'] else 0
            logger.info(f"  {code} {name} 现 {cur:.2f} ({chg:+.2f}%)")

            if cur <= bs and not FIRED.get((code, 'strong')):
                push(f"## 💰💰 {name} ({code}) 跌至 {cur:.2f}\n触发 buy_strong (≤{bs})！")
                FIRED[(code, 'strong')] = True
            elif cur <= bz and not FIRED.get((code, 'zone')):
                push(f"## 💰 {name} ({code}) 跌至 {cur:.2f}\n触发 buy_zone (≤{bz})")
                FIRED[(code, 'zone')] = True

        time.sleep(60)  # 1 分钟轮询


if __name__ == '__main__':
    main()
