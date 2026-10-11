"""Same-condition speed test for the local models (the speeds in results.md come from evaluation runs whose
conditions differed: downloads in parallel, memory mapping on or off, different answer lengths).

Each model, alone on the machine: unload everything, one warm-up call (records load time), then 3 timed calls with
the same ~1.5k-token prompt (a run number at the very start defeats Ollama's prompt cache) and exactly 256 output
tokens. temperature 0, 16k context, no memory mapping, thinking off.

  python eval/speed_bench.py                 # all models below -> eval/speed.md, eval/speed.json
  python eval/speed_bench.py gemma4:12b      # some
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent import OLLAMA  # noqa: E402

MODELS = ["gemma4:e2b", "gemma4:e4b", "gemma4:12b-it-qat", "gemma4:12b", "gemma4:12b-it-q8_0",
          "gemma4:26b-a4b-it-qat", "qwen3:8b", "qwen3:14b", "qwen3.8:27b"]
OUT = Path(__file__).resolve().parent
LOG = (Path(__file__).resolve().parent.parent / "demo" / "bots" / "binance_a.log").read_text(encoding="utf-8")
PROMPT = ("Here is a trading bot's log. Explain, step by step and in detail, what happened to each position and "
          "each virtual order, in time order, and what the operator should check next.\n\n" + LOG * 3)


NOTES = """Notes
- Measured 2026-10-11 with the previous demo log as the prompt (same length within a few lines); the demo was
  rebuilt with the demo rules on 10-12. Output speed does not depend on what the log says.
- No memory column: Ollama's `/api/ps` reported 1.4 GB for gemma4:12b while `nvidia-smi` showed about 8 GB in use
  (10.7 GB on the card, about 2.4 GB at idle). *On GPU* is still the share `/api/ps` reports.
- gemma4:12b (Q4_K_M) at about 75 tokens/s is confirmed by wall-clock time (73.8 tok/s). Reading about 7 GB of weights
  once per token on this card (about 288 GB/s) allows a little over 40 tokens/s, so the runtime must be doing more than
  one plain forward pass per token for this tag (speculative decoding, for example). Not verified. The QAT tag (Q4_0)
  of the same model runs at about 31 tokens/s."""


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{OLLAMA}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1200) as r:
        return json.loads(r.read())


def loaded() -> list[dict]:
    with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=10) as r:
        return json.loads(r.read())["models"]


def unload_all() -> None:
    for m in loaded():
        post("/api/generate", {"model": m["name"], "keep_alive": 0})


def call(model: str, n: int) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": f"Run {n}. {PROMPT}"}], "stream": False,
            "think": False, "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 256, "use_mmap": False}}
    try:
        return post("/api/chat", body)
    except urllib.error.HTTPError:  # a model without a thinking switch
        body.pop("think")
        return post("/api/chat", body)


def bench(model: str) -> dict:
    unload_all()
    t0 = time.time()
    warm = call(model, 0)
    load_s = warm.get("load_duration", 0) / 1e9
    ps = next((m for m in loaded() if m["name"] in (model, model + ":latest")), {})
    runs = [call(model, i) for i in (1, 2, 3)]
    gen = [r["eval_count"] / (r["eval_duration"] / 1e9) for r in runs]
    pre = [r["prompt_eval_count"] / (r["prompt_eval_duration"] / 1e9) for r in runs]
    unload_all()
    return {"model": model, "size_gb": round(ps.get("size", 0) / 1e9, 1),
            "gpu_share": round(ps.get("size_vram", 0) / ps["size"], 2) if ps.get("size") else None,
            "load_s": round(load_s, 1), "prompt_tokens": runs[0]["prompt_eval_count"], "out_tokens": runs[0]["eval_count"],
            "prompt_tok_s": round(statistics.median(pre)), "gen_tok_s": round(statistics.median(gen), 1),
            "gen_tok_s_runs": [round(g, 1) for g in gen], "wall_s": round(time.time() - t0)}


def main():
    models = sys.argv[1:] or MODELS
    path = OUT / "speed.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for m in models:
        rows[m] = bench(m)
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(json.dumps(rows[m]), flush=True)
    lines = ["# Speed, same conditions (RTX 4060 Ti 16 GB, 32 GB RAM, Ollama)", "",
             "One model at a time; a ~1.5k-token prompt, 256 output tokens, median of 3 runs after a warm-up. "
             "Thinking off, temperature 0, 16k context, no memory mapping. `eval/speed_bench.py`.", "",
             "| Model | On GPU | Load (s) | Prompt tok/s | Output tok/s | Output runs |",
             "|---|---|---|---|---|---|"]
    for m in MODELS:
        if m in rows:
            r = rows[m]
            gpu = f"{r['gpu_share']:.0%}" if r["gpu_share"] is not None else "—"
            lines.append(f"| {m} | {gpu} | {r['load_s']} | {r['prompt_tok_s']} | **{r['gen_tok_s']}** "
                         f"| {', '.join(map(str, r['gen_tok_s_runs']))} |")
    lines += ["", NOTES]
    (OUT / "speed.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
