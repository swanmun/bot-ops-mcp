"""Which trading rules the server describes and checks signals with.

The rules in this repository (demo_strategy.py) are demo rules, used with the demo data. The live bots' rules are
private: on the server they are loaded from a file outside the repository with the same interface,
BOT_OPS_STRATEGY (default BOT_OPS_DIR/bot_ops_strategy.py). Demo mode always uses the demo rules. A live server without
that file falls back to the demo rules and says so in every result that depends on them.

[한국어] 서버가 어떤 매매 규칙으로 설명하고 신호를 확인하는지 정한다.

이 레포에 있는 규칙(demo_strategy.py)은 데모 데이터와 함께 쓰는 데모 규칙이다. 실제 운영 봇의 규칙은 비공개다.
서버에서는 같은 인터페이스를 가진 레포 밖 파일 BOT_OPS_STRATEGY(기본값 BOT_OPS_DIR/bot_ops_strategy.py)에서
읽어 온다. 데모 모드는 늘 데모 규칙을 쓴다. 그 파일이 없는 실제 서버는 데모 규칙으로 대신하고,
규칙에 기대는 모든 결과에 그 사실을 적는다.
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
    """Added to results that depend on the rules when they are not the expected ones.

    [한국어] 쓰는 규칙이 기대한 규칙이 아닐 때, 규칙에 기대는 결과에 덧붙인다.
    """
    return {} if SOURCE in ("demo", "live") else {"rules_warning": SOURCE}
