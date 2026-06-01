"""Pytest path bootstrap.

Some QA agents run pytest from a working directory outside the repository root.
Ensure top-level packages such as `scripts` and `broker` remain importable during
collection regardless of the invocation cwd.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
