"""Checks that combine bot files and exchange data. All read-only.

[한국어] 봇 파일과 거래소 데이터를 함께 보는 점검. 모두 읽기 전용이다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import botfiles, config, strategy
from .exchange import ExchangeError, client


def _side_name(side: int) -> str:
    return "LONG" if side > 0 else "SHORT"


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def _bar_ms(bar: str | None) -> int | None:
    """The bot's bar key ('2026-10-09 12:00:00', UTC open time of the bar in which the order was made).

    [한국어] 봇의 봉 키('2026-10-09 12:00:00'). 주문을 만든 봉의 시작 시각(UTC)이다.
    """
    if not bar:
        return None
    return int(datetime.strptime(bar[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _order_findings(account: str, st: dict, ex) -> list[dict]:
    """Waiting virtual orders against the H4 bars since they were made (public market data).
    The bot cancels an order once price goes past its stop, and enters once price reaches the entry — an order
    that is still waiting after either happened means the bot missed it.

    [한국어] 대기 중인 가상 주문을 만들어진 뒤의 H4 봉(공개 시장 데이터)과 맞대어 본다.
    봇은 가격이 손절가를 넘어가면 주문을 취소하고, 가격이 진입가에 닿으면 진입한다. 둘 중 하나가 일어났는데
    주문이 아직 대기 중이면 봇이 그것을 놓친 것이다.
    """
    out = []
    running = botfiles.is_running(account)
    down = " The bot is not running, so nothing acts on this order." if running is False else ""
    for sym, o in st["orders"].items():
        side, where = o["side"], f"{sym} {_side_name(o['side'])} virtual order"
        try:
            k = ex.klines_4h(sym, 300)
        except ExchangeError:
            continue  # market data unavailable — no verdict rather than a wrong one / 시장 데이터를 못 받음 — 틀린 판정을 내느니 판정하지 않는다
        t0 = _bar_ms(o.get("bar"))
        bars = [b for b in k if t0 is None or int(b[0]) >= t0]
        stop_at = next((b[0] for b in bars if (side > 0 and float(b[3]) <= o["sl"]) or (side < 0 and float(b[2]) >= o["sl"])), None)
        entry_at = next((b[0] for b in bars if (side > 0 and float(b[2]) >= o["trig"]) or (side < 0 and float(b[3]) <= o["trig"])), None)
        has_leg = any(l["side"] == side and l.get("bar") == o.get("bar") for l in st["legs"].get(sym, []))
        if entry_at is not None and (stop_at is None or entry_at <= stop_at) and not has_leg:
            item = {"level": "problem", "where": where,
                    "what": f"price reached the entry {o['trig']} in the H4 bar opening {_utc(entry_at)} UTC but the bot has "
                            f"no leg from this signal — the entry failed (search_log for ⚠️) or the bot was not running.{down}"}
        elif stop_at is not None:
            item = {"level": "warn", "where": where,
                    "what": f"price went past the stop {o['sl']} in the H4 bar opening {_utc(stop_at)} UTC; the bot should "
                            f"have cancelled this order.{down}"}
        else:
            item = {"level": "ok", "where": where,
                    "what": f"still valid: price has stayed between the stop {o['sl']} and the entry {o['trig']} since the "
                            f"order was made ({o.get('bar') or '?'} UTC)"}
        out.append(item)
    return out


def check_positions(account: str) -> dict:
    """Compare the bot's legs with what the exchange actually holds.

    Findings (each with level ok / warn / problem):
      - exchange position size vs sum of the bot's legs, per symbol and side
      - every leg has its own stop order on the exchange with the same quantity and price
      - stop orders that no leg owns, positions the bot does not know about
      - waiting virtual orders whose entry or stop price has already been reached (missed entry / missed cancel)

    [한국어] 봇의 레그를 거래소가 실제로 들고 있는 것과 비교한다.

    결과 항목(각각 level ok / warn / problem):
      - 심볼·방향별로 거래소 포지션 크기와 봇 레그 수량 합계
      - 레그마다 수량과 가격이 같은 자기 손절 주문이 거래소에 있는지
      - 어느 레그의 것도 아닌 손절 주문(주인 없는 손절), 봇이 모르는 포지션
      - 진입가나 손절가에 이미 닿았는데 아직 대기 중인 가상 주문(놓친 진입 / 놓친 취소)
    """
    st = botfiles.read_state(account)
    ex = client(account)
    try:
        positions = ex.positions()
        stops = ex.open_stops()
    except ExchangeError as e:
        return {"account": account, "exchange": "unavailable", "reason": str(e),
                "bot_legs": {s: len(v) for s, v in st["legs"].items()}}

    pos = {}
    for p in positions:
        side = {"LONG": 1, "SHORT": -1}.get(p.get("positionSide"))
        amt = abs(float(p.get("positionAmt", 0)))
        if side and amt > 0:
            pos[(p["symbol"], side)] = {"qty": amt, "avg_entry": float(p.get("entryPrice", 0))}
    stop_by_id = {str(o.get("algoId")): o for o in stops}
    owned = set()
    findings = []

    symbols = sorted({s for s, _ in pos} | set(st["legs"]))
    for sym in symbols:
        for side in (1, -1):
            legs = [l for l in st["legs"].get(sym, []) if l["side"] == side]
            ex_pos = pos.get((sym, side))
            leg_qty = round(sum(float(l["qty"]) for l in legs), 8)
            where = f"{sym} {_side_name(side)}"
            if not legs and not ex_pos:
                continue
            if legs and not ex_pos:
                findings.append({"level": "problem", "where": where,
                                 "what": f"bot has {len(legs)} leg(s) ({leg_qty}) but the exchange shows no position — "
                                         "closed outside the bot or a stop filled and the bot has not synced yet"})
                continue
            if ex_pos and not legs:
                findings.append({"level": "warn", "where": where,
                                 "what": f"exchange position {ex_pos['qty']} that the bot does not track (manual entry?). "
                                         "The bot will not manage or count it"})
                continue
            diff = round(ex_pos["qty"] - leg_qty, 8)
            if abs(diff) > 1e-9:
                findings.append({"level": "warn", "where": where,
                                 "what": f"size mismatch: exchange {ex_pos['qty']} vs legs {leg_qty} (diff {diff:+}). "
                                         + ("Extra size is probably a manual entry; an opposite signal would close it too."
                                            if diff > 0 else "Part was closed outside the bot.")})
            else:
                findings.append({"level": "ok", "where": where, "what": f"size matches ({leg_qty}, {len(legs)} leg(s))"})
            for i, leg in enumerate(legs, 1):
                sid = str(leg.get("stop_id")) if leg.get("stop_id") else None
                o = stop_by_id.get(sid) if sid else None
                if o is None:
                    findings.append({"level": "problem", "where": f"{where} leg {i}",
                                     "what": "no stop order on the exchange for this leg (the bot re-places it on its next check if it is running)"})
                    continue
                owned.add(sid)
                trig = float(o.get("triggerPrice") or 0)
                n_before = len(findings)
                if leg.get("sl") is not None and abs(trig - float(leg["sl"])) > 1e-6 * max(1.0, trig):
                    findings.append({"level": "warn", "where": f"{where} leg {i}",
                                     "what": f"stop price differs: exchange {trig} vs bot {leg['sl']}"})
                if str(o.get("quantity")) not in ("", "None") and abs(float(o["quantity"]) - float(leg["qty"])) > 1e-9:
                    findings.append({"level": "warn", "where": f"{where} leg {i}",
                                     "what": f"stop quantity {o['quantity']} differs from leg quantity {leg['qty']}"})
                if len(findings) == n_before:  # say it out loud, so "are all stops in place?" has a direct answer / 이상이 없어도 분명히 적는다. 그래야 "손절이 다 걸려 있나?"에 바로 답이 된다
                    findings.append({"level": "ok", "where": f"{where} leg {i}",
                                     "what": f"stop order on the exchange at {botfiles.num(trig)} for {leg['qty']} (price and quantity match the bot)"})
    for sid, o in stop_by_id.items():
        if sid not in owned:
            findings.append({"level": "warn", "where": f"{o.get('symbol')} {o.get('positionSide')}",
                             "what": f"stop order at {o.get('triggerPrice')} that no leg owns (left over from an old bot or a manual order)"})
    findings += _order_findings(account, st, ex)
    worst = "problem" if any(f["level"] == "problem" for f in findings) else "warn" if any(f["level"] == "warn" for f in findings) else "ok"
    return {"account": account, "overall": worst, "findings": findings,
            "virtual_orders_waiting": {s: _side_name(o["side"]) for s, o in st["orders"].items()}}


def pnl_summary(account: str, days: int = 7) -> dict:
    """Realized PnL, commission and funding over the last `days`, as % of the current wallet balance and in R.
    Dollar amounts are never returned.

    [한국어] 최근 `days`일 동안의 실현 손익, 수수료, 펀딩비를 현재 지갑 잔고 대비 %와 R로 낸다.
    달러 금액은 절대 돌려주지 않는다.
    """
    ex = client(config.check_account(account))
    end = config.now_ms()
    start = end - days * 86_400_000
    try:
        rows = ex.income(start, end)
        bal = ex.wallet_balance()
    except ExchangeError as e:
        return {"account": account, "exchange": "unavailable", "reason": str(e)}
    if bal <= 0:
        return {"account": account, "error": "wallet balance is zero"}
    sums = {"REALIZED_PNL": 0.0, "COMMISSION": 0.0, "FUNDING_FEE": 0.0}
    closes = 0
    by_symbol = {}
    for r in rows:
        t = r.get("incomeType")
        if t in sums:
            v = float(r["income"])
            sums[t] += v
            by_symbol[r.get("symbol", "?")] = by_symbol.get(r.get("symbol", "?"), 0.0) + v
            closes += t == "REALIZED_PNL"
    net = sum(sums.values()) / bal * 100
    # strings with the % sign: as bare numbers (net_pct: -0.039), small models read them as fractions and
    # reported -3.9 % (eval n1/n5, 2026-10-11)
    # % 기호를 붙인 문자열로 준다. 그냥 숫자(net_pct: -0.039)로 주면 작은 모델이 이를 비율로 읽고
    # -3.9 %라고 보고했다(eval n1/n5, 2026-10-11)
    return {"account": account, "days": days,
            "net": f"{_pct(net)} of balance ({net / strategy.RISK_PCT:+.2f} R)",
            "realized": _pct(sums["REALIZED_PNL"] / bal * 100), "commission": _pct(sums["COMMISSION"] / bal * 100),
            "funding": _pct(sums["FUNDING_FEE"] / bal * 100),
            "closing_fills": closes,
            "by_symbol": {s: _pct(v / bal * 100) for s, v in sorted(by_symbol.items())},
            "note": f"percent of the current wallet balance; 1 R = {strategy.RISK_PCT}% of balance (the risk of one trade)",
            **strategy.note()}


def _pct(v: float) -> str:
    """-0.0391 -> '-0.039%' (3 decimals, trailing zeros dropped, sign always shown).

    [한국어] 소수 셋째 자리까지 쓰고, 끝의 0은 지우고, 부호는 늘 붙인다.
    """
    s = f"{round(v, 3):+.3f}".rstrip("0").rstrip(".")
    return ("+0" if s in ("+0", "-0") else s) + "%"


def market_snapshot(symbol: str) -> dict:
    """Where price is relative to the H4 moving average of the rules and whether the last completed bars form a signal.

    [한국어] 규칙이 쓰는 H4 이동평균에 비해 가격이 어디 있는지, 마지막 완성 봉들이 신호를 이루는지 본다.
    """
    symbol = symbol.upper()
    ex = client()
    try:
        k = ex.klines_4h(symbol, 300)
        tick = ex.tick_size(symbol)
    except ExchangeError as e:
        return {"symbol": symbol, "market": "unavailable", "reason": str(e)}
    highs = [float(r[2]) for r in k]
    lows = [float(r[3]) for r in k]
    closes = [float(r[4]) for r in k]
    p = strategy.MA_PERIOD

    def ma_at(i: int) -> float:  # MA of the p closes ending at bar -i / 봉 -i에서 끝나는 종가 p개의 MA
        return sum(closes[len(closes) - i - p + 1:len(closes) - i + 1]) / p

    ma = ma_at(2)  # of completed bars / 완성된 봉 기준
    last_close = closes[-2]
    touch_ago = next((i for i in range(2, 60) if lows[-i] <= ma_at(i) <= highs[-i]), None)
    sig = strategy.find_signal(highs, lows, closes, tick)
    return {"symbol": symbol, "last_completed_bar_utc": _utc(k[-2][0]), "current_bar_open_utc": _utc(k[-1][0]),
            "last_completed_close": last_close, "ma_period": p, "ma": round(ma, 6),
            "distance_from_ma_pct": round((last_close - ma) / ma * 100, 2),
            "side_of_ma": "above" if last_close > ma else "below",
            "completed_bars_since_price_touched_ma": touch_ago - 2 if touch_ago else "60+",
            "signal_on_last_completed_bars": sig,
            "note": "A signal here becomes a virtual order in the bot at the start of the current bar.", **strategy.note()}
