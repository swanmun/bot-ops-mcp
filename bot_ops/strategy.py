"""Which trading rules the server describes and checks signals with.

The rules in this repository (demo_strategy.py) are demo rules, used with the demo data. The live bots' rules are
private: on the server they are loaded from a file outside the repository with the same interface,
BOT_OPS_STRATEGY (default BOT_OPS_DIR/bot_ops_strategy.py). Demo mode always uses the demo rules. A live server without
that file falls back to the demo rules and says so in every result that depends on them.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from . import config, demo_strategy


def _load():
    if config.DEMO:
        return demo_strategy, "demo"
    path = Path(os.environ.get("BOT_OPS_STRATEGY", config.BOT_DIR / "bot_ops_strategy.py"))
    if not path.is_file():
        return demo_strategy, f"DEMO RULES: no live rules file at {path.name}, so these are not the live bots' rules"
    spec = importlib.util.spec_from_file_location("bot_ops_live_strategy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, "live"


_S, SOURCE = _load()
MA_PERIOD: int = _S.MA_PERIOD
RISK_PCT: float = float(os.environ.get("BOT_OPS_RISK", _S.RISK_PCT))
RULES: str = _S.RULES
find_signal = _S.find_signal


def note() -> dict:
    """Added to results that depend on the rules when they are not the expected ones."""
    return {} if SOURCE in ("demo", "live") else {"rules_warning": SOURCE}
