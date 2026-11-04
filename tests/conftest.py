"""Pytest path setup for Megila tests.

``tests/assets`` is not an installed package. Putting it on ``sys.path`` lets
``make_sample`` import under plain pytest, without a ``pyproject.toml``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
if str(_ASSETS) not in sys.path:
    sys.path.insert(0, str(_ASSETS))
