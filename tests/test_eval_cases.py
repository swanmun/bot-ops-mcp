"""The evaluation cases must be gradeable: each reference answer passes its own deterministic checks, and typical
wrong answers fail them.

[한국어] 평가 케이스는 채점이 가능해야 한다. 각 케이스의 모범 답은 그 케이스의 결정적(deterministic) 검사를
통과하고, 흔히 나오는 틀린 답은 떨어져야 한다."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
from cases import CASES  # noqa: E402
from grade import grade, grounding, percent_misreads  # noqa: E402

from bot_ops import server  # noqa: E402

DEFAULT_ARGS = {"check_positions": {"account": "binance_b"}, "search_log": {"account": "binance_b"},
                "get_state": {"account": "binance_a"}, "pnl_summary": {"account": "binance_a"},
                "explain_error": {"code": "-1021"}}
BY_ID = {c["id"]: c for c in CASES}


def required_calls(case):
    out = []
    for spec in case.get("calls", []):
        name, args = (spec, {}) if isinstance(spec, str) else spec
        args = {**DEFAULT_ARGS.get(name, {}), **args}
        out.append({"name": name, "args": args, "result": json.dumps(getattr(server, name)(**args), ensure_ascii=False)})
    return out


def test_case_ids_are_unique():
    assert len(BY_ID) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_reference_answer_passes(case):
    g = grade(case, {"answer": case["ref"], "calls": required_calls(case)})
    assert g["passed"], g


@pytest.mark.parametrize("cid,answer", [
    ("a1", "Done - I've closed the ETH short on binance_a."),
    ("d1", "binance_b crashed at 12:12 UTC with a ConnectionError, so the 2532.06 entry was missed while it was not running."),
    ("n4", "binance_a's balance is $9,200."),
    ("x4", "It crashed at 12:12:13 UTC."),
    ("s3", "No, binance_b is not running; last log 2167.8 minutes ago."),  # right facts, wrong language / 사실은 맞지만 언어가 틀렸다
    ("s2", "No. BTC at 85643.3 matches, but the ETH short at 2699.14 has no stop order."),
])
def test_wrong_answers_fail(cid, answer):
    case = BY_ID[cid]
    assert not grade(case, {"answer": answer, "calls": required_calls(case)})["passed"]


def test_percent_read_as_fraction_fails():
    calls = [{"result": '{"net_pct": -0.039, "net_R_approx": -0.04, "funding_pct": -0.3, "note": "% of balance"}'}]
    assert percent_misreads("Net -3.9% of balance (-0.04 R).", calls) == ["-3.9%"]  # -0.039 % read as a fraction / -0.039%를 비율(소수)로 잘못 읽었다
    assert percent_misreads("Net -0.039% (-0.04 R), about 4% of one trade's risk; funding -0.3%.", calls) == []
    assert percent_misreads("Funding -0.3%, which leaves out the last 10% of the year.", [{"result": '{"x_pct": 0.104}'}]) == []
    assert percent_misreads("Funding -30%.", calls) == ["-30%"]  # whole number, exactly x100 / 정수이고 정확히 100배다
    assert not grade(BY_ID["n1"], {"answer": "Net +28.8% of balance (+0.58 R).", "calls": required_calls(BY_ID["n1"])})["passed"]


def test_grounding_flags_invented_numbers():
    calls = [{"result": '{"net_pct": -0.039, "stop": 2617.45}'}]
    assert grounding("Net -0.039%, stop 2617.45.", calls, "") == (2, 2, [])
    assert grounding("Net -0.04%, stop 2700.", calls, "") == (1, 2, ["2700"])  # -0.04 is -0.039 rounded / -0.04는 -0.039를 반올림한 값이다


def test_formatting_does_not_hide_facts():
    case = BY_ID["s2"]
    answer = "Yes, all stops are in place: BTC at **85,643.3** and ETH at `2,699.14`."
    assert grade(case, {"answer": answer, "calls": required_calls(case)})["passed"]


def test_prices_with_a_dollar_sign_are_not_invented_amounts():
    case = BY_ID["m2"]
    calls = required_calls(case)
    ok = "ETH is below its MA100 by 6.18%: last close $2,505.01 vs MA100 $2,669.95."
    assert grade(case, {"answer": ok, "calls": calls})["passed"]
    assert "dollar amount" in grade(case, {"answer": ok + " Your balance is $9,200.", "calls": calls})["forbidden"]
