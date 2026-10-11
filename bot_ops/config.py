"""Where the bot files live and which files the server may read.

The server only ever reads three kinds of files inside BOT_OPS_DIR:
  state_<account>.json   bot state (virtual orders, legs)
  <account>.log          bot console log
  .env.mcp               read-only exchange keys for this server (never the bots' own .env files)

Environment variables
  BOT_OPS_DIR    folder with the bots (default: the folder above this package)
  BOT_OPS_DEMO   "1" = use the bundled fake data in demo/ (no network, no real account)
  BOT_OPS_ENV    path of the key file (default: BOT_OPS_DIR/.env.mcp)
  BOT_OPS_RISK   risk per trade in % of balance, used to turn % into R (default: from the rules, see strategy.py)
  BOT_OPS_STRATEGY  file with the live bots' rules (default BOT_OPS_DIR/bot_ops_strategy.py; private, not in the repo)
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEMO_DIR = PACKAGE_DIR.parent / "demo"
DEMO = os.environ.get("BOT_OPS_DEMO", "").lower() in ("1", "true", "yes")
BOT_DIR = DEMO_DIR / "bots" if DEMO else Path(os.environ.get("BOT_OPS_DIR", PACKAGE_DIR.parent)).resolve()

ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")


def _demo_clock() -> dict:
    f = DEMO_DIR / "clock.json"
    return json.loads(f.read_text(encoding="utf-8")) if DEMO and f.exists() else {}


_CLOCK = _demo_clock()
DEMO_NOW_MS = (int(datetime.strptime(_CLOCK["now_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000)
               if "now_utc" in _CLOCK else None)
# The demo server logs in its local time like the real one (KST); bar times stay UTC
DEMO_LOG_TZ = timezone(timedelta(hours=_CLOCK.get("log_utc_offset_hours", 0)), _CLOCK.get("log_tz_name", "UTC"))


def now_ms() -> int:
    """Current time in ms. Demo mode: the fixed moment the demo data describes, so answers do not drift."""
    return DEMO_NOW_MS if DEMO_NOW_MS is not None else int(time.time() * 1000)


def accounts() -> list[str]:
    """Accounts = bots that have a state file (state_<account>.json)."""
    return sorted(p.stem[len("state_"):] for p in BOT_DIR.glob("state_*.json"))


def check_account(account: str) -> str:
    """Only known account names — never a path. Raises ValueError otherwise."""
    if not ACCOUNT_RE.match(account or "") or account not in accounts():
        raise ValueError(f"unknown account '{account}'. Known: {', '.join(accounts()) or 'none'}")
    return account


def state_path(account: str) -> Path:
    return BOT_DIR / f"state_{check_account(account)}.json"


def log_path(account: str) -> Path:
    return BOT_DIR / f"{check_account(account)}.log"


def read_keys() -> dict[str, str]:
    """KEY=VALUE lines from .env.mcp. Missing file = no exchange access (tools say so)."""
    path = Path(os.environ.get("BOT_OPS_ENV", BOT_DIR / ".env.mcp"))
    if DEMO or not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        if v:
            out[k.strip()] = v
    return out
