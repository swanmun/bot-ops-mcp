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

[한국어] 봇 파일이 어디 있는지, 서버가 어떤 파일을 읽어도 되는지 정한다.

서버는 BOT_OPS_DIR 안에서 세 종류의 파일만 읽는다:
  state_<account>.json   봇 상태(가상 주문, 레그)
  <account>.log          봇 콘솔 로그
  .env.mcp               이 서버 전용 읽기 전용 거래소 키(봇 자신의 .env 파일은 절대 읽지 않는다)

환경 변수
  BOT_OPS_DIR    봇이 있는 폴더(기본값: 이 패키지의 상위 폴더)
  BOT_OPS_DEMO   "1"이면 demo/에 같이 들어 있는 가짜 데이터를 쓴다(네트워크 없음, 실제 계좌 없음)
  BOT_OPS_ENV    키 파일 경로(기본값: BOT_OPS_DIR/.env.mcp)
  BOT_OPS_RISK   거래당 위험(잔고 대비 %). %를 R로 바꿀 때 쓴다(기본값: 규칙에서 가져온다. strategy.py 참고)
  BOT_OPS_STRATEGY  실제 운영 봇의 규칙 파일(기본값 BOT_OPS_DIR/bot_ops_strategy.py. 비공개라 레포에 없다)
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
# 데모 서버도 실제 서버처럼 현지 시각(KST)으로 로그를 쓴다. 봉 시각은 그대로 UTC다
DEMO_LOG_TZ = timezone(timedelta(hours=_CLOCK.get("log_utc_offset_hours", 0)), _CLOCK.get("log_tz_name", "UTC"))


def now_ms() -> int:
    """Current time in ms. Demo mode: the fixed moment the demo data describes, so answers do not drift.

    [한국어] 현재 시각(ms). 데모 모드에서는 데모 데이터가 그리는 고정된 시점을 쓴다. 그래야 답이 시간에 따라 달라지지 않는다.
    """
    return DEMO_NOW_MS if DEMO_NOW_MS is not None else int(time.time() * 1000)


def accounts() -> list[str]:
    """Accounts = bots that have a state file (state_<account>.json).

    [한국어] 계정 = 상태 파일(state_<account>.json)이 있는 봇.
    """
    return sorted(p.stem[len("state_"):] for p in BOT_DIR.glob("state_*.json"))


def check_account(account: str) -> str:
    """Only known account names — never a path. Raises ValueError otherwise.

    [한국어] 아는 계정 이름만 받는다. 경로는 절대 받지 않는다. 그 밖에는 ValueError를 낸다.
    """
    if not ACCOUNT_RE.match(account or "") or account not in accounts():
        raise ValueError(f"unknown account '{account}'. Known: {', '.join(accounts()) or 'none'}")
    return account


def state_path(account: str) -> Path:
    return BOT_DIR / f"state_{check_account(account)}.json"


def log_path(account: str) -> Path:
    return BOT_DIR / f"{check_account(account)}.log"


def read_keys() -> dict[str, str]:
    """KEY=VALUE lines from .env.mcp. Missing file = no exchange access (tools say so).

    [한국어] .env.mcp의 KEY=VALUE 줄을 읽는다. 파일이 없으면 거래소에 접근하지 않는다(도구가 그렇다고 알려 준다).
    """
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
