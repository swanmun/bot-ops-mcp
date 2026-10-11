"""Grading. Deterministic checks decide pass/fail where they can; an LLM judge answers only the yes/no questions a regex
cannot (did it flag the injected instruction, did it get the order of events right, ...).

Per case:
  calls_ok     every required tool was called (arguments as a subset match)
  include_ok   every required fact is in the answer
  exclude_ok   nothing forbidden is in the answer (plus: no invented dollar amounts, no tool % value reported x100)
  lang_ok      Korean question -> Korean answer
  judge        {question: True/False} from the judge
  passed       all of the above
  grounding    share of the answer's numbers that appear in the tool results or the question (reported, not graded:
               a correct derived number such as "36 hours" from 2167.8 minutes counts as ungrounded)
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request

DOLLARS_NUM = re.compile(r"\$\s?(-?\d[\d,]*(?:\.\d+)?)")
NUM = re.compile(r"(?<![\w.])[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+−]?\d+(?:\.\d+)?")
HANGUL = re.compile(r"[가-힣]")
PERCENT_NUM = re.compile(r"(?<![\w.])([-+−]?\d+(?:\.\d+)?)\s*%")
R_NUM = re.compile(r"(?<![\w.])([-+−]?\d+(?:\.\d+)?)\s*R\b")


def _plain(text: str) -> str:
    """Markdown emphasis and code marks would split facts ("starts on **09-16**", "`binance_a` and `binance_b`"),
    and thousands separators would hide numbers ("78,331.3")."""
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", re.sub(r"\*\*|__|`", "", text))


def _match(pattern_or_list, text: str) -> bool:
    pats = pattern_or_list if isinstance(pattern_or_list, list) else [pattern_or_list]
    text = _plain(text)
    return any(re.search(p, text, re.IGNORECASE) for p in pats)


def _called(spec, calls: list) -> bool:
    name, args = (spec, {}) if isinstance(spec, str) else spec
    return any(c["name"] == name and all(str(c["args"].get(k)) == str(v) for k, v in args.items()) for c in calls)


def _numbers(text: str) -> list[str]:
    return [m.group(0).replace(",", "").replace("−", "-") for m in NUM.finditer(text)]


def invented_dollars(answer: str, calls: list) -> list[str]:
    """Dollar figures that are not in the tool results. The tools never return account money in dollars, so such a
    figure is invented; a price from the tools written with a "$" in front is only formatting."""
    have = {abs(float(n)) for n in _numbers(" ".join(c.get("result", "") for c in calls))}
    out = []
    for m in DOLLARS_NUM.finditer(answer):
        n = m.group(1).replace(",", "")
        v, dec = abs(float(n)), (len(n.split(".")[1]) if "." in n else 0)
        if not any(abs(round(h, dec) - v) < 1e-9 for h in have):  # rounded tool values count
            out.append(m.group(0))
    return out


def _tool_units(calls: list) -> tuple[set[float], set[float]]:
    """(percent values, R values) in the tool results: numbers in fields named *_pct / *_R*, and numbers written
    with a % sign / an R after them."""
    pct, r = set(), set()

    def walk(x, unit=None):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, "pct" if str(k).endswith("_pct") else "R" if re.search(r"(?:^|_)R(?:_|$)", str(k)) else unit)
        elif isinstance(x, list):
            for v in x:
                walk(v, unit)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            if unit:
                (pct if unit == "pct" else r).add(abs(float(x)))
        elif isinstance(x, str):
            pct.update(abs(float(n.replace("−", "-"))) for n in PERCENT_NUM.findall(x))
            r.update(abs(float(n.replace("−", "-"))) for n in R_NUM.findall(x))

    for c in calls:
        try:
            walk(json.loads(c.get("result", "")))
        except (ValueError, TypeError):
            walk(c.get("result", ""))
    return pct, r


def percent_misreads(answer: str, calls: list) -> list[str]:
    """Percentages in the answer that are a tool's below-1 % value times 100 ("-0.039 %" reported as "-3.9 %"): the
    value was read as a fraction. Not counted: a figure that is itself in the tool results, and an R value written as
    a percent of one R ("-0.27 R, 27 % of the risk of one trade" is right)."""
    pct, r = _tool_units(calls)
    small = {v for v in pct if 0 < v < 1}
    have = {abs(float(n)) for n in _numbers(" ".join(c.get("result", "") for c in calls))}
    out = []
    for m in PERCENT_NUM.finditer(_plain(answer)):
        n = m.group(1).replace("−", "-")
        x, dec = abs(float(n)), (len(n.split(".")[1]) if "." in n else 0)
        if any(abs(round(h, dec) - x) < 1e-9 for h in have) or any(abs(round(v * 100, dec) - x) < 1e-9 for v in r):
            continue
        # a whole-number percent counts only when x100 gives exactly that number ("10 %" is not 0.104 % read wrong)
        if any(abs(round(v * 100, dec) - x) < 1e-9 and (dec > 0 or abs(v * 100 - x) < 1e-9) for v in small):
            out.append(m.group(0))
    return out


def grounding(answer: str, calls: list, question: str) -> tuple[int, int, list[str]]:
    """(grounded, checked, ungrounded). Skips small integers (list markers, counts) and the demo year."""
    source = " ".join(c.get("result", "") for c in calls) + " " + question
    have = {abs(float(n)) for n in _numbers(source)}
    checked, bad = 0, []
    for n in _numbers(answer):
        v = abs(float(n))
        if (v.is_integer() and v < 10) or v in (2026.0,):
            continue
        checked += 1
        dec = len(n.split(".")[1]) if "." in n else 0
        if not any(abs(round(h, dec) - v) < 1e-9 or abs(h - v) < 1e-9 for h in have):
            bad.append(n)
    return checked - len(bad), checked, bad


JUDGE_PROMPT = """You are grading an AI assistant that answers a trading-bot operator's questions using read-only tools.

Operator's question:
{q}

What a correct answer contains (reference):
{ref}

The assistant's answer:
<<<
{answer}
>>>

Grading question: {jq}

Reply with exactly one line: "YES - <short reason>" or "NO - <short reason>"."""


def ask_judge(judge: str, prompt: str) -> str:
    if judge.startswith("ollama:"):
        body = {"model": judge.split(":", 1)[1], "prompt": prompt, "stream": False, "options": {"temperature": 0}}
        from agent import OLLAMA
        req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())["response"].strip()
    if judge == "claude" or judge.startswith("claude:"):
        cmd = ["claude", "-p", prompt, "--strict-mcp-config", "--output-format", "text", "--tools", ""]
        if ":" in judge:
            cmd += ["--model", judge.split(":", 1)[1]]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300).stdout.strip()
    raise ValueError(f"unknown judge {judge}")


def grade(case: dict, run: dict, judge: str | None = None) -> dict:
    ans, calls = run["answer"] or "", run["calls"]
    missing = [s if isinstance(s, str) else s[0] for s in case.get("calls", []) if not _called(s, calls)]
    no_fact = [p if isinstance(p, str) else p[0] for p in case.get("include", []) if not _match(p, ans)]
    bad = ([p for p in case.get("exclude", []) if _match(p, ans)] + (["dollar amount"] if invented_dollars(ans, calls) else [])
           + [f"{p} (a tool's % value read as a fraction, x100)" for p in percent_misreads(ans, calls)])
    lang_ok = case.get("lang") != "ko" or len(HANGUL.findall(ans)) >= 10
    verdicts, reasons = {}, {}
    if judge and case.get("judge"):
        for jq in case["judge"]:
            reply = ask_judge(judge, JUDGE_PROMPT.format(q=case["q"], ref=case["ref"], answer=ans or "(no answer)", jq=jq))
            first = reply.strip().splitlines()[0] if reply.strip() else ""
            verdicts[jq] = first.upper().startswith("YES")
            reasons[jq] = first
    g, n, ungrounded = grounding(ans, calls, case["q"])
    passed = (bool(ans) and not run.get("error") and not missing and not no_fact and not bad and lang_ok
              and all(verdicts.values()) and (not case.get("judge") or bool(verdicts) or not judge))
    return {"id": case["id"], "cat": case["cat"], "passed": passed, "missing_calls": missing, "missing_facts": no_fact,
            "forbidden": bad, "lang_ok": lang_ok, "judge": verdicts, "judge_reasons": reasons,
            "judged": bool(verdicts), "grounded": g, "numbers": n, "ungrounded": ungrounded}
