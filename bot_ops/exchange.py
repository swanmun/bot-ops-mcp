"""Binance USDT-M futures — read-only.

Safety by construction:
  - Only HTTP GET, and only the endpoints in ALLOWED. There is no code path that can place,
    cancel or modify an order.
  - Use a separate API key created with "Enable Reading" only (and an IP restriction).
    Keys come from .env.mcp:  RO_KEY_<ACCOUNT>=...  RO_SECRET_<ACCOUNT>=...
  - Demo mode serves the same calls from demo/exchange/<account>.json and demo/market/<symbol>_4h.json.

[한국어] Binance USDT-M 선물. 읽기 전용이다.

구조 자체로 안전하게 만든다:
  - HTTP GET만 쓰고, ALLOWED에 있는 엔드포인트만 부른다. 주문을 내거나 취소하거나 바꿀 수 있는
    코드 경로는 아예 없다.
  - "Enable Reading"만 켜서 만든 별도 API 키를 쓴다(IP 제한도 건다).
    키는 .env.mcp의 RO_KEY_<ACCOUNT>, RO_SECRET_<ACCOUNT> 줄에서 읽는다.
  - 데모 모드에서는 같은 호출에 demo/exchange/<account>.json과 demo/market/<symbol>_4h.json으로 답한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from . import config

BASE = "https://fapi.binance.com"
ALLOWED = {  # path -> needs signature / 경로 -> 서명이 필요한지
    "/fapi/v1/time": False,
    "/fapi/v1/klines": False,
    "/fapi/v1/exchangeInfo": False,
    "/fapi/v1/ticker/bookTicker": False,
    "/fapi/v3/positionRisk": True,
    "/fapi/v1/openAlgoOrders": True,
    "/fapi/v3/balance": True,
    "/fapi/v1/income": True,
}


class ExchangeError(Exception):
    pass


class Binance:
    def __init__(self, account: str | None = None):
        self.account = account
        keys = config.read_keys()
        tag = (account or "").upper()
        self.key = keys.get(f"RO_KEY_{tag}")
        self.secret = keys.get(f"RO_SECRET_{tag}")
        self._offset = None

    def _get(self, path: str, params: dict | None = None):
        if path not in ALLOWED:
            raise ExchangeError(f"endpoint not allowed (read-only server): {path}")
        params = dict(params or {})
        headers = {}
        if ALLOWED[path]:
            if not (self.key and self.secret):
                raise ExchangeError(f"no read-only key for '{self.account}' (add RO_KEY_/RO_SECRET_ to .env.mcp)")
            if self._offset is None:
                self._offset = self._get("/fapi/v1/time")["serverTime"] - int(time.time() * 1000)
            params["timestamp"] = int(time.time() * 1000 + self._offset)
            params["recvWindow"] = 10000
            q = urllib.parse.urlencode(params)
            params["signature"] = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self.key
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:  # Binance puts {"code", "msg"} in the body / Binance는 응답 본문에 {"code", "msg"}를 담는다
            try:
                body = json.loads(e.read())
                raise ExchangeError(f"Binance {body.get('code')}: {body.get('msg')}") from None
            except (ValueError, KeyError):
                raise ExchangeError(f"HTTP {e.code} on {path}") from None
        except urllib.error.URLError as e:
            raise ExchangeError(f"network error on {path}: {e.reason}") from None

    # --- account (signed) ---
    # --- 계정(서명 필요) ---
    def positions(self, symbol: str | None = None) -> list[dict]:
        return self._get("/fapi/v3/positionRisk", {"symbol": symbol} if symbol else {})

    def open_stops(self, symbol: str | None = None) -> list[dict]:
        res = self._get("/fapi/v1/openAlgoOrders", {"symbol": symbol} if symbol else {})
        return res.get("orders", []) if isinstance(res, dict) else res

    def wallet_balance(self) -> float:
        for b in self._get("/fapi/v3/balance"):
            if b.get("asset") == "USDT":
                return float(b["balance"])
        return 0.0

    def income(self, start_ms: int, end_ms: int) -> list[dict]:
        out, start = [], start_ms
        while True:  # paginate, 1000 rows per call / 페이지를 넘기며 받는다. 한 번에 1000줄
            rows = self._get("/fapi/v1/income", {"startTime": start, "endTime": end_ms, "limit": 1000})
            out += rows
            if len(rows) < 1000:
                return out
            start = rows[-1]["time"] + 1

    # --- public ---
    # --- 공개(서명 불필요) ---
    def klines_4h(self, symbol: str, limit: int = 300) -> list[list]:
        return self._get("/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": limit})

    def tick_size(self, symbol: str) -> float:
        for s in self._get("/fapi/v1/exchangeInfo")["symbols"]:
            if s["symbol"] == symbol:
                return float(next(f["tickSize"] for f in s["filters"] if f["filterType"] == "PRICE_FILTER"))
        raise ExchangeError(f"unknown symbol {symbol}")


class DemoBinance:
    """Same interface, fake data. Used by tests and the public demo.

    [한국어] 인터페이스는 같고 데이터는 가짜다. 테스트와 공개 데모에서 쓴다.
    """

    def __init__(self, account: str | None = None):
        self.account = account

    def _acct(self) -> dict:
        f = config.DEMO_DIR / "exchange" / f"{config.check_account(self.account)}.json"
        if not f.exists():
            raise ExchangeError(f"no read-only key for '{self.account}' (demo has no exchange data)")
        return json.loads(f.read_text(encoding="utf-8"))

    def positions(self, symbol=None):
        return [p for p in self._acct()["positions"] if symbol in (None, p["symbol"])]

    def open_stops(self, symbol=None):
        return [o for o in self._acct()["open_stops"] if symbol in (None, o["symbol"])]

    def wallet_balance(self):
        return self._acct()["wallet_balance"]

    def income(self, start_ms, end_ms):
        return [r for r in self._acct()["income"] if start_ms <= r["time"] <= end_ms]

    def klines_4h(self, symbol, limit=300):
        f = config.DEMO_DIR / "market" / f"{symbol}_4h.json"
        if not f.exists():
            raise ExchangeError(f"demo has no market data for {symbol}")
        rows = [r for r in json.loads(f.read_text(encoding="utf-8")) if r[0] <= config.now_ms()]
        return rows[-limit:]

    def tick_size(self, symbol):
        return {"BTCUSDT": 0.1, "ETHUSDT": 0.01}.get(symbol, 0.01)


def client(account: str | None = None):
    return DemoBinance(account) if config.DEMO else Binance(account)
