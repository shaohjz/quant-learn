"""
notify.py — 企微自定义机器人 Webhook 推送封装（第二版）
======================================================================
依赖: requests (pip install requests)

功能:
  1. 从 config.yaml 读 notify.wecom_webhook
  2. 提供 send_text / send_markdown / send_card
  3. CLI 支持 --stdin 参数（从 stdin 读内容，方便 Agent 管道传入）

用法:
  from notify import send_text, send_markdown
  send_text('Hello World')
  send_markdown('## 标题\n**加粗**')

  # CLI:
  echo "内容" | python notify.py text --stdin
  echo "## 标题" | python notify.py markdown --stdin
  python notify.py text --content "直接传内容"
  python notify.py markdown --content "## 标题"
  python notify.py card --title "标题" --content "描述" --url "https://..."
"""

import sys
from pathlib import Path
import yaml
import argparse
import sys
from pathlib import Path
import yaml
import requests

# ── 读 config.yaml ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
WEBHOOK_URL = (cfg.get('notify') or {}).get('wecom_webhook', '')
if not WEBHOOK_URL:
    print('[notify] ⚠️ config.yaml 缺少 notify.wecom_webhook', file=sys.stderr)

# ── 基础 POST ─────────────────────────────────────────────────────
def _post(payload: dict, timeout: int = 10) -> dict:
    """POST 到企微 Webhook，返回解析后的 JSON。"""
    if not WEBHOOK_URL:
        print('[notify] ⚠️ Webhook URL 未配置，仅打印不发送', file=sys.stderr)
        print(f'[notify] payload={payload}', file=sys.stderr)
        return {'errcode': -1, 'errmsg': 'webhook_not_configured'}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        result = r.json()
        if result.get('errcode', 0) != 0:
            print(f"[notify] ⚠️ 企微返回错误: {result}", file=sys.stderr)
        return result
    except Exception as ex:
        print(f'[notify] ⚠️ POST 失败: {ex}', file=sys.stderr)
        return {'errcode': -1, 'errmsg': str(ex)}


# ── 公开 API ─────────────────────────────────────────────────────
def send_text(content: str, mentioned_list: list = None,
             mentioned_mobile_list: list = None) -> dict:
    """发送纯文本消息。"""
    payload = {
        'msgtype': 'text',
        'text': {
            'content': content,
            'mentioned_list': mentioned_list or [],
            'mentioned_mobile_list': mentioned_mobile_list or [],
        }
    }
    return _post(payload)


def send_markdown(content: str, mentioned_list: list = None) -> dict:
    """发送 Markdown 消息（企微支持有限 Markdown）。"""
    payload = {
        'msgtype': 'markdown',
        'markdown': {
            'content': content,
            'mentioned_list': mentioned_list or [],
        }
    }
    return _post(payload)


def send_card(title: str, description: str = '', url: str = '',
              picurl: str = '') -> dict:
    """发送卡片消息（企微称为 'news' 类型）。"""
    payload = {
        'msgtype': 'news',
        'news': {
            'articles': [
                {
                    'title': title,
                    'description': description,
                    'url': url,
                    'picurl': picurl,
                }
            ]
        }
    }
    return _post(payload)


def send_raw(payload: dict) -> dict:
    """直接发送原始 payload（高级用法）。"""
    return _post(payload)


# ── CLI 入口 ─────────────────────────────────────────────────────
def cmd_text(args):
    content = sys.stdin.read().strip() if args.stdin else args.content
    if not content:
        print('[notify] ⚠️ 内容为空', file=sys.stderr)
        sys.exit(1)
    mentioned = args.mentioned.split(',') if args.mentioned else []
    result = send_text(content, mentioned_list=mentioned)
    print(f'result={result}')
    sys.exit(0 if result.get('errcode', 0) == 0 else 1)


def cmd_markdown(args):
    content = sys.stdin.read().strip() if args.stdin else args.content
    if not content:
        print('[notify] ⚠️ 内容为空', file=sys.stderr)
        sys.exit(1)
    result = send_markdown(content)
    print(f'result={result}')
    sys.exit(0 if result.get('errcode', 0) == 0 else 1)


def cmd_card(args):
    result = send_card(args.title, description=args.content, url=args.url)
    print(f'result={result}')
    sys.exit(0 if result.get('errcode', 0) == 0 else 1)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='企微机器人 Webhook 推送')
    sub = parser.add_subparsers(dest='command')

    # text
    p_text = sub.add_parser('text', help='发送纯文本')
    p_text.add_argument('--content', default='')
    p_text.add_argument('--mentioned', default='')
    p_text.add_argument('--stdin', action='store_true', help='从 stdin 读内容')
    p_text.set_defaults(func=cmd_text)

    # markdown
    p_mark = sub.add_parser('markdown', help='发送 Markdown')
    p_mark.add_argument('--content', default='')
    p_mark.add_argument('--stdin', action='store_true', help='从 stdin 读内容')
    p_mark.set_defaults(func=cmd_markdown)

    # card
    p_card = sub.add_parser('card', help='发送卡片')
    p_card.add_argument('--title', required=True)
    p_card.add_argument('--content', default='')
    p_card.add_argument('--url', default='')
    p_card.set_defaults(func=cmd_card)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)
