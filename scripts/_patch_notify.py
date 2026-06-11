"""Patch: 无异动时也推送通知"""
from pathlib import Path

f = Path('scripts/intraday_scanner.py')
text = f.read_text(encoding='utf-8')

# 找到目标行
old_lines = '        print(f"✓ {now.strftime(\'%H:%M\')} 无新异动")\r\n        logger.info("无新异动")'
new_lines = '''        print(f"✓ {now.strftime(\'%H:%M\')} 无新异动")
        logger.info("无新异动")
        # 无异动也推送简短通知
        if not args.no_webhook:
            no_msg = f"✅ 盘中扫描 ({now.strftime('%H:%M')}) | {len(filtered)} 只过滤→{len(candidates)} 只候选→未发现符合条件的异动"
            push_webhook(no_msg)'''

# normalize line endings for matching
text_n = text.replace('\r\n', '\n')
old_n = '        print(f"✓ {now.strftime(\'%H:%M\')} 无新异动")\n        logger.info("无新异动")'

if old_n in text_n:
    text_n = text_n.replace(old_n, new_lines)
    f.write_text(text_n, encoding='utf-8')
    print("✓ Patched")
else:
    # try with unicode escaped
    old_n2 = '        print(f"\u2713 {now.strftime(\'%H:%M\')} \u65e0\u65b0\u5f02\u52a8")\n        logger.info("\u65e0\u65b0\u5f02\u52a8")'
    if old_n2 in text_n:
        text_n = text_n.replace(old_n2, new_lines)
        f.write_text(text_n, encoding='utf-8')
        print("✓ Patched (alt)")
    else:
        # manual line search
        lines = text_n.split('\n')
        for i, line in enumerate(lines):
            if '无新异动' in line and 'print' in line:
                print(f"Found at line {i+1}: {repr(line)}")
                break
        print("✗ Could not patch automatically")
