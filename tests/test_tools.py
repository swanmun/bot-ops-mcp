"""Tools against the demo data, through a real MCP client (in-process)."""
import asyncio
import json

import pytest
from mcp.client.client import Client

from bot_ops import demo_strategy, exchange, redact, strategy
from bot_ops.server import mcp


def call(name, **args):
    async def go():
        async with Client(mcp) as c:
            res = await c.call_tool(name, args)
            return res.structured_content or json.loads(res.content[0].text)
    return asyncio.run(go())


def test_tools_are_listed_and_read_only():
    async def go():
        async with Client(mcp) as c:
            return (await c.list_tools()).tools
    tools = asyncio.run(go())
    names = {t.name for t in tools}
    assert names == {"list_bots", "get_state", "check_positions", "search_log", "explain_error",
                     "pnl_summary", "market_snapshot", "strategy_rules"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_list_bots():
    out = call("list_bots")
    bots = {b["account"]: b for b in out["bots"]}
    assert set(bots) == {"binance_a", "binance_b"}
    assert bots["binance_a"]["running"] is True and bots["binance_b"]["running"] is False
    assert bots["binance_a"]["virtual_orders"] == [] and bots["binance_b"]["virtual_orders"] == ["BTCUSDT", "ETHUSDT"]
    # fixed demo clock 2026-10-09 15:20 UTC: last lines 15:00:30 and 10-08 03:12:13
    assert bots["binance_a"]["minutes_since_last_log"] == 19.5
    assert bots["binance_b"]["minutes_since_last_log"] == 2167.8


def test_get_state():
    out = call("get_state", account="binance_a")
    btc, eth = out["legs"]["BTCUSDT"][0], out["legs"]["ETHUSDT"][0]
    assert btc["side"] == eth["side"] == "SHORT" and btc["stop_at_or_beyond_entry"] is False
    assert eth["age_hours"] == 30.8  # entered 10-08 08:32:41 UTC, clock 10-09 15:20
    assert out["virtual_orders"] == {}
    b = call("get_state", account="binance_b")
    assert {s: o["side"] for s, o in b["virtual_orders"].items()} == {"BTCUSDT": "SHORT", "ETHUSDT": "SHORT"}
    assert b["legs"]["BTCUSDT"][0]["adopted_from_old_bot"] is True


@pytest.mark.parametrize("tool", ["get_state", "check_positions", "search_log", "pnl_summary"])
@pytest.mark.parametrize("bad", ["../../etc/passwd", "binance_a/../x", "state_binance_a", "binance_c", ""])
def test_unknown_account_is_an_error_not_a_path(tool, bad):
    out = call(tool, account=bad)
    assert "unknown account" in out["error"]
    assert "passwd" not in json.dumps(out).replace(bad, "")  # the error names the known accounts, nothing else


def test_check_positions_ok_and_problems():
    a = call("check_positions", account="binance_a")
    assert a["overall"] == "ok"
    stops = [f for f in a["findings"] if f["where"].endswith("leg 1")]
    assert len(stops) == 2 and all(f["level"] == "ok" and "match the bot" in f["what"] for f in stops)
    b = call("check_positions", account="binance_b")
    text = json.dumps(b["findings"], ensure_ascii=False)
    assert b["overall"] == "problem"
    assert "size mismatch" in text and "+0.01" in text
    assert "no leg owns" in text
    for sym, bar in (("BTCUSDT", "2026-10-08 04:00"), ("ETHUSDT", "2026-10-08 08:00")):  # both after the 03:12 crash
        missed = next(f for f in b["findings"] if f["where"] == f"{sym} SHORT virtual order")
        assert missed["level"] == "problem" and bar in missed["what"] and "not running" in missed["what"]


def test_demo_tools_agree_with_each_other():
    """The demo bot state must be explainable from the demo market data (one story across tools)."""
    for sym, tick in (("BTCUSDT", 0.1), ("ETHUSDT", 0.01)):
        order = call("get_state", account="binance_b")["virtual_orders"][sym]
        bars = [r for r in exchange.client().klines_4h(sym, 1000) if r[0] <= 1791360000000]  # up to the 10-07 08:00 bar
        sig = demo_strategy.find_signal([float(r[2]) for r in bars], [float(r[3]) for r in bars],
                                        [float(r[4]) for r in bars], tick)
        assert sig["side"] == order["side"]
        assert (sig["entry"], sig["one_R_level"], sig["stop"]) == (order["entry_price"], order["one_R_level"], order["stop"])


def test_search_log_problems_and_redaction():
    out = call("search_log", account="binance_a", only_problems=True)
    assert any("-2019" in ln for ln in out["lines"])
    allout = call("search_log", account="binance_a", contains="진입 (")
    assert all("$<amount>" in ln for ln in allout["lines"])  # dollar amounts never leave the server


def test_explain_error():
    assert "filling" in call("explain_error", code="retcode=10030")["meaning"]
    assert call("explain_error", code="-2021")["what_to_do"].startswith("Expected")
    unknown = call("explain_error", code="-9999")
    assert unknown["meaning"] == "not in the known list" and "-2019" in unknown["known_codes"]


def test_time_zones_are_stated():
    assert call("search_log", account="binance_a", limit=1)["log_times"].startswith("server local time, KST (UTC+09:00)")
    assert "UTC" in call("get_state", account="binance_a")["times"]


def test_float_noise_is_trimmed():
    from bot_ops.botfiles import num
    assert num(75358.69090909092) == 75358.691 and num(166.65999999999985) == 166.66
    assert num(2617.45) == 2617.45 and num(None) is None and num("0.011") == "0.011"


def test_injected_instruction_is_returned_as_data():
    out = call("search_log", account="binance_b", only_problems=True)
    assert any("Note to the AI assistant" in ln for ln in out["lines"])
    assert "never instructions" in out["untrusted"]
    assert "never follow" in mcp.instructions


def test_search_log_limit_is_clamped():
    assert len(call("search_log", account="binance_a", limit=-5)["lines"]) == 1
    assert len(call("search_log", account="binance_a", limit=10_000)["lines"]) == call("search_log", account="binance_a")["matched"]


def test_pnl_summary_has_no_dollars():
    out = call("pnl_summary", account="binance_a", days=7)  # fixed clock: same answer every day
    assert out["closing_fills"] == 2 and out["realized"] == "+0.332%"  # both longs stopped at the shorts' 1R levels
    assert out["net"] == "+0.288% of balance (+0.58 R)"  # with the % sign: a bare number was read as a fraction
    assert not any(k in json.dumps(out) for k in ("9200", "6.49"))
    assert call("pnl_summary", account="binance_a", days=1000)["days"] == 90
    assert call("pnl_summary", account="binance_a", days=0)["days"] == 1


def test_market_snapshot():
    out = call("market_snapshot", symbol="btcusdt")
    assert out["symbol"] == "BTCUSDT" and out["side_of_ma"] == "below" and out["ma_period"] == 100
    assert out["last_completed_bar_utc"] == "2026-10-09 08:00" and out["current_bar_open_utc"] == "2026-10-09 12:00"
    assert out["signal_on_last_completed_bars"] is None
    assert call("market_snapshot", symbol="ETHUSDT")["signal_on_last_completed_bars"] is None
    assert call("market_snapshot", symbol="XRPUSDT")["market"] == "unavailable"


def test_exchange_client_refuses_non_whitelisted_endpoints():
    b = exchange.Binance("binance_a")
    with pytest.raises(exchange.ExchangeError, match="not allowed"):
        b._get("/fapi/v1/order", {"symbol": "BTCUSDT"})


def test_redaction_patterns():
    s = redact.text("key=abc " + "A" * 64 + " tok 123456789:" + "x" * 35 + " ip 10.1.2.3 loss $1,234.50")
    assert "A" * 64 not in s and "x" * 35 not in s and "10.1.2.3" not in s and "1,234" not in s


def test_demo_rule_signal():
    # flat closes at 100 (= the MA), bar -4 closes below it, bars -3/-2 close above it -> long signal
    closes, highs, lows = [100.0] * 300, [100.5] * 300, [99.5] * 300
    lows[-4], highs[-4], closes[-4] = 98.5, 100.4, 99.0
    for i in (-3, -2):
        lows[i], highs[i], closes[i] = 101.0, 102.0, 101.5
    sig = demo_strategy.find_signal(highs, lows, closes, tick=0.1)
    assert sig["side"] == "LONG" and sig["stop"] == pytest.approx(98.4) and sig["one_R_level"] == pytest.approx(102.1)
    assert sig["entry"] == pytest.approx(98.4 + 56 * 0.1)  # 1.5 x 37 ticks, rounded to a whole tick


def test_demo_mode_uses_demo_rules():
    assert strategy.SOURCE == "demo" and strategy.RULES == demo_strategy.RULES
    assert "demo" in call("strategy_rules")["rules"].splitlines()[0]


@pytest.mark.parametrize("with_file", [False, True])
def test_live_rules_file_is_loaded_or_its_absence_is_flagged(tmp_path, with_file):
    """Live mode reads the private rules from BOT_OPS_DIR/bot_ops_strategy.py; without it, results say so."""
    import os
    import subprocess
    import sys
    if with_file:
        (tmp_path / "bot_ops_strategy.py").write_text(
            "MA_PERIOD = 7\nRISK_PCT = 2.0\nRULES = 'private rules'\ndef find_signal(h, l, c, t):\n    return None\n")
    env = {k: v for k, v in os.environ.items() if k not in ("BOT_OPS_DEMO", "BOT_OPS_STRATEGY", "BOT_OPS_RISK")}
    env["BOT_OPS_DIR"] = str(tmp_path)
    out = subprocess.run([sys.executable, "-c", "from bot_ops import strategy as s; print(s.SOURCE, s.MA_PERIOD, s.RISK_PCT, s.note())"],
                         env=env, capture_output=True, text=True, check=True).stdout
    if with_file:
        assert out.startswith("live 7 2.0 {}")
    else:
        assert out.startswith("DEMO RULES") and "rules_warning" in out
