"""测试收益率曲线 API"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.app import app
import json

with app.test_client() as client:
    response = client.get('/api/equity_curve')
    data = response.json
    print(json.dumps(data, indent=2, ensure_ascii=False))
