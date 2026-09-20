#!/usr/bin/env python3
"""Build ppt-master visual-styles/_catalog.json from on-disk cards.

Usage (from agent/):
  python scripts/build-visual-style-catalog.py
  # or
  webppt-agent styles-catalog
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from webppt_agent.ppt_master.styles import rebuild_catalog, visual_styles_dir  # noqa: E402


def main() -> int:
    path = rebuild_catalog()
    print(f"[ok] wrote {path}")
    print(f"[ok] styles_dir={visual_styles_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
