"""Fix cmd_report: add timedelta import + fix the function"""
with open(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\pm_cli.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Fix line 207: add 'from datetime import timedelta' after 'now = datetime.now()'
# Actually, simpler: fix the import at top, or fix cmd_report to use correct reference
# The file has: from datetime import datetime, time as _dt_time
# Need to add timedelta to that import line

for i, line in enumerate(lines):
    if line.strip() == "from datetime import datetime, time as _dt_time":
        lines[i] = "from datetime import datetime, time as _dt_time, timedelta\n"
        print(f"Fixed import at line {i+1}")
        break

with open(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\pm_cli.py", "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Done. Testing...")
import subprocess
r = subprocess.run(
    ["C:\\Users\\Administrator\\.openclaw\\workspace\\quant-learn\\.venv\\Scripts\\python.exe",
     "scripts/pm_cli.py", "report"],
    cwd=r"C:\Users\Administrator\.openclaw\workspace\quant-learn",
    capture_output=True, text=True, timeout=10
)
print("STDOUT:", r.stdout[:500])
print("STDERR:", r.stderr[:300])
