"""Static knowledge the model can look up: error codes. (The strategy rules are in strategy.py.)

[한국어] 모델이 찾아볼 수 있는 고정 지식: 오류 코드. (매매 규칙은 strategy.py에 있다.)
"""
from __future__ import annotations

ERRORS = {
    # Binance USDT-M futures
    # Binance USDT-M 선물
    "-1003": ("Too many requests (rate limit).", "The bot backs off and retries. Persistent: two bots on one IP polling too fast."),
    "-1021": ("Request timestamp outside recvWindow — the server clock drifted.",
              "Check `timedatectl` (NTP synced). The bot re-syncs its clock on this error and every hour."),
    "-2010": ("New order rejected by the exchange.", "Read the message that follows the code; often balance or price limits."),
    "-2011": ("Cancel rejected — the order is already gone (filled, cancelled or unknown).",
              "Usually harmless: a stop already triggered or was removed. Check positions vs legs."),
    "-2014": ("API key format invalid.", "The key in the .env file is wrong or truncated."),
    "-2015": ("Invalid API key, IP or permissions.",
              "Key deleted, IP restriction does not match the server IP, or Futures permission off."),
    "-2019": ("Margin is insufficient.", "Balance too small for the order at the account's leverage. The bot retries; it notifies once."),
    "-2021": ("Order would immediately trigger — the stop level is already past the current price.",
              "Expected when moving a stop to break-even or 1R after price already crossed it: the bot closes that leg at market instead."),
    "-2022": ("ReduceOnly order rejected.", "Close size larger than the position (position already reduced)."),
    "-4164": ("Order notional below the exchange minimum.", "Balance × risk too small for this symbol; the bot skips the entry."),
    # MetaTrader 5 trade server return codes
    # MetaTrader 5 거래 서버 반환 코드
    "10004": ("MT5 requote.", "Price moved; the bot retries on the next check."),
    "10006": ("MT5 request rejected.", "Broker rejected the request; read the comment field."),
    "10013": ("MT5 invalid request.", "Malformed request fields (symbol, volume, type)."),
    "10014": ("MT5 invalid volume.", "Lot outside min/max/step for the symbol."),
    "10015": ("MT5 invalid price.", "Price stale or off the allowed range."),
    "10016": ("MT5 invalid stops.", "Stop too close to price or on the wrong side (e.g. break-even after price already crossed)."),
    "10018": ("MT5 market closed.", "Outside trading hours; the bot keeps the virtual order and retries when the market opens."),
    "10019": ("MT5 not enough money.", "Margin too small for the lot."),
    "10027": ("MT5 autotrading disabled in the terminal.", "Turn on 'Algo Trading' in the MT5 terminal."),
    "10030": ("MT5 unsupported filling mode.",
              "The symbol does not accept the order's fill policy (e.g. IOC). Fixed 2026-10-09: the bots pick IOC → FOK → RETURN "
              "from symbol_info.filling_mode. A bot built before that keeps failing on such symbols."),
}
