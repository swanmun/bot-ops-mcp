"""Demo trading rules: the rules the bundled demo data (demo/) was built with.

They are NOT the live bots' rules. Those are private and stay on the server (see strategy.py). A rules module has:
  MA_PERIOD      moving average the rules use (H4 closes)
  RISK_PCT       risk per trade in % of balance (turns % of balance into R)
  RULES          the rules as text, for the strategy_rules tool
  find_signal()  the signal on the last completed bars, or None

[한국어] 데모 매매 규칙. 같이 들어 있는 데모 데이터(demo/)를 만들 때 쓴 규칙이다.

실제 운영 봇의 규칙이 아니다. 그 규칙은 비공개라 서버에만 있다(strategy.py 참고). 규칙 모듈에는 다음이 있다:
  MA_PERIOD      규칙이 쓰는 이동평균(H4 종가 기준)
  RISK_PCT       거래당 위험(잔고 대비 %). 잔고 대비 %를 R로 바꾼다
  RULES          규칙을 글로 적은 것. strategy_rules 도구가 쓴다
  find_signal()  마지막 완성 봉들의 신호. 없으면 None
"""
from __future__ import annotations

MA_PERIOD = 100
RISK_PCT = 0.5
ENTRY_R = 1.5  # entry, in signal units (stop 0, 1R level 1) / 진입가, 신호 단위(손절 0, 1R 레벨 1)
BREAK_EVEN_R = 1.0  # break-even trigger, in initial risk beyond the entry / 본전 이동 조건. 진입가에서 초기 위험의 몇 배를 더 가야 하는지

RULES = f"""\
Strategy rules used by the demo bots (demo data only; the live bots' rules are private)

Signal (H4, completed bars): price crosses the {MA_PERIOD}-period moving average and two closes confirm it.
  Long: close[-4] below its MA{MA_PERIOD}, close[-3] and close[-2] above theirs.  Short: mirror image.
Levels (signal units): stop = lowest low of bars -4..-2 - 1 tick (long). 1R level = highest high of bars -3..-2 + 1 tick.
  Entry = stop + {ENTRY_R} x (1R level - stop), i.e. the "{ENTRY_R}R point". So the trade's initial risk = {ENTRY_R} signal units.
Virtual orders: the entry is NOT placed on the exchange. The bot remembers it (state file) and buys/sells at market
  when price reaches it, if a slot is free. Cancelled when price goes past the stop, or a completed bar closes back
  across the MA{MA_PERIOD}.
  The check uses the CURRENT price on each loop (every ~30 s): it enters only if the price right now is at or beyond the
  entry. If the entry was touched while the bot was down and price has come back, a restarted bot does not enter late;
  it keeps waiting for price to reach the entry again (or cancels the order by the rules above).
Position size: {RISK_PCT}% of balance at risk, computed from the ACTUAL fill price to the stop (late fills get smaller size).
Break-even: when a completed H4 bar after entry reaches entry + {BREAK_EVEN_R} x initial risk, the stop moves to entry +/- 1 tick.
Opposite signal: when it becomes a virtual order, stops of opposite positions are pulled to the new signal's 1R level.
Adding: a new same-direction signal becomes another virtual order; at most 4 open legs per account (BTC + ETH).
Binance specifics: hedge mode; same-side entries merge into one exchange position, so the bot tracks each entry as
  a 'leg' (qty, entry, stop, initial risk) and places one STOP_MARKET per leg for that leg's quantity.
"""


def _ma(closes: list[float], end: int) -> float:
    """MA of the MA_PERIOD closes ending at index `end` (negative).

    [한국어] 인덱스 `end`(음수)에서 끝나는 종가 MA_PERIOD개의 MA.
    """
    n = len(closes)
    return sum(closes[n + end - MA_PERIOD + 1:n + end + 1]) / MA_PERIOD


def find_signal(highs, lows, closes, tick) -> dict | None:
    """Signal at the start of the current bar (the last list item is the bar in progress; -4..-2 are completed).

    [한국어] 현재 봉이 시작될 때의 신호. 리스트의 마지막 항목은 진행 중인 봉이고, -4..-2가 완성된 봉이다.
    """
    if len(closes) < MA_PERIOD + 6:
        return None
    c = closes
    if c[-4] < _ma(c, -4) and c[-3] > _ma(c, -3) and c[-2] > _ma(c, -2):
        side, level, stop = 1, max(highs[-3], highs[-2]) + tick, min(lows[-4], lows[-3], lows[-2]) - tick
    elif c[-4] > _ma(c, -4) and c[-3] < _ma(c, -3) and c[-2] < _ma(c, -2):
        side, level, stop = -1, min(lows[-3], lows[-2]) - tick, max(highs[-4], highs[-3], highs[-2]) + tick
    else:
        return None
    unit = round(side * (level - stop) / tick)
    if unit <= 0:
        return None
    return {"side": "LONG" if side > 0 else "SHORT", "entry": round(stop + side * round(ENTRY_R * unit) * tick, 8),
            "one_R_level": round(level, 8), "stop": round(stop, 8)}
