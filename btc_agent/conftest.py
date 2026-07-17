"""Ensures `btc_agent` is importable as a package (from btc_agent.risk
import ...) regardless of where pytest is invoked from. Inserts this
directory's *parent*, not this directory itself - inserting btc_agent/
directly would put flat modules named `risk`/`backtest` on sys.path,
shadowing the equity scaffold's top-level risk/ and backtest/ packages
when the full repo suite runs from the root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
