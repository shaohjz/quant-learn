"""Run swing_pool_builder and show results"""
import subprocess, json, sys, os
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn")
os.chdir(ROOT)

# Run swing_pool_builder
result = subprocess.run(
    [sys.executable, "scripts/swing_pool_builder.py", "--top", "20", "--mode", "auto", "--force"],
    capture_output=True, text=True, timeout=120
)
print("=== STDOUT ===")
print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
if result.stderr:
    print("=== STDERR ===")
    print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
print(f"\n=== EXIT CODE: {result.returncode} ===")

# Show latest pool file
pool_dir = ROOT / "output" / "swing_pool"
if pool_dir.exists():
    files = sorted(pool_dir.glob("*.json"))
    if files:
        latest = files[-1]
        print(f"\n=== Latest pool: {latest.name} ===")
        data = json.loads(latest.read_text(encoding="utf-8"))
        if isinstance(data, list):
            print(f"Total stocks in pool: {len(data)}")
            for i, s in enumerate(data[:10], 1):
                score = s.get("score", s.get("total_score", "?"))
                name = s.get("name", s.get("stock_name", "?"))
                code = s.get("code", s.get("stock_code", "?"))
                reason = s.get("reason", s.get("entry_reason", ""))
                print(f"  {i}. {name}({code}) score={score}  {reason}")
            if len(data) > 10:
                print(f"  ... and {len(data)-10} more")
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
