"""REQ-007 暗色/浅色主题切换静态回归测试。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_template(name: str) -> str:
    return (ROOT / "web" / "templates" / name).read_text(encoding="utf-8")


def test_dashboard_has_persistent_theme_toggle():
    html = _read_template("index.html")
    assert ':root[data-theme="dark"]' in html
    assert "id=\"theme-toggle\"" in html
    assert "quantlearn-theme" in html
    assert "function toggleTheme()" in html
    assert "localStorage.setItem(THEME_KEY" in html
    # 图表颜色应跟随 CSS 变量，避免暗色模式下仍使用浅色硬编码。
    assert "getCssVar('--chart-text')" in html
    assert "getCssVar('--chart-grid')" in html


def test_pm_board_shares_theme_preference():
    html = _read_template("pm.html")
    assert ':root[data-theme="dark"]' in html
    assert "id=\"theme-toggle\"" in html
    assert "quantlearn-theme" in html
    assert "function toggleTheme()" in html
    assert "var(--column-bg)" in html
    assert "var(--input-bg)" in html
