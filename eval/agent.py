"""The assistants under test. Each takes a question and returns
{"answer": str, "calls": [{"name", "args", "result"}], "seconds": float, "error": str | None}.

  ollama:<model>   a local model in a plain tool-calling loop against the demo server (in-process MCP client).
                   It gets the server's own instructions as the system prompt, like an MCP host would pass them.
  claude           Claude Code in headless mode (`claude -p`) with only the demo server connected.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["BOT_OPS_DEMO"] = "1"  # before bot_ops is imported
sys.path.insert(0, str(ROOT))

from mcp.client.client import Client  # noqa: E402

from bot_ops.server import mcp as server  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_HOST", "localhost:11434")
OLLAMA = OLLAMA if OLLAMA.startswith("http") else "http://" + OLLAMA  # the env var is often set without a scheme
MAX_STEPS = 10


def _result_text(res) -> str:
    if res.structured_content is not None:
        return json.dumps(res.structured_content, ensure_ascii=False)
    return "\n".join(getattr(c, "text", "") for c in res.content)


def _ollama_chat(model: str, messages: list, tools: list) -> dict:
    body = {"model": model, "messages": messages, "tools": tools, "stream": False,
            "options": {"temperature": 0, "num_ctx": 16384,
                        # no memory-mapping: otherwise the weights also sit in RAM while they are on the GPU, and
                        # models that spill out of 16 GB of VRAM ran a 32 GB machine out of memory (2026-10-10)
                        "use_mmap": False}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def _ollama_loaded(model: str) -> dict:
    """Model size and how much of it sits in GPU memory, from /api/ps (the model is still loaded after a run)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=10) as r:
            m = next((m for m in json.loads(r.read())["models"] if m["name"] in (model, model + ":latest")), None)
    except Exception:
        return {}
    return {"size_gb": round(m["size"] / 1e9, 1), "gpu_share": round(m["size_vram"] / m["size"], 2)} if m else {}


async def _run_ollama(model: str, question: str) -> dict:
    calls = []
    st = {"out_tokens": 0, "gen_s": 0.0, "prompt_tokens": 0, "prompt_s": 0.0}
    async with Client(server) as c:
        tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                   "parameters": t.input_schema}}
                 for t in (await c.list_tools()).tools]
        messages = [{"role": "system", "content": server.instructions}, {"role": "user", "content": question}]
        for _ in range(MAX_STEPS):
            resp = await asyncio.to_thread(_ollama_chat, model, messages, tools)
            st["out_tokens"] += resp.get("eval_count", 0)
            st["gen_s"] += resp.get("eval_duration", 0) / 1e9
            st["prompt_tokens"] += resp.get("prompt_eval_count", 0)
            st["prompt_s"] += resp.get("prompt_eval_duration", 0) / 1e9
            msg = resp["message"]
            messages.append(msg)
            if not msg.get("tool_calls"):
                return {"answer": msg.get("content", ""), "calls": calls, "stats": {**st, **_ollama_loaded(model)}}
            for tc in msg["tool_calls"]:
                name, args = tc["function"]["name"], tc["function"].get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args or "{}")
                try:
                    text = _result_text(await c.call_tool(name, args))
                except Exception as e:  # unknown tool, bad arguments: tell the model, like a host would
                    text = json.dumps({"error": f"{type(e).__name__}: {e}"})
                calls.append({"name": name, "args": args, "result": text})
                messages.append({"role": "tool", "tool_name": name, "content": text})
        return {"answer": "", "calls": calls, "error": f"no final answer after {MAX_STEPS} steps",
                "stats": {**st, **_ollama_loaded(model)}}


def _run_claude(question: str, model: str | None = None) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]  # demo/mcp.json runs `python`
    cmd = ["claude", "-p", question, "--mcp-config", "demo/mcp.json", "--strict-mcp-config",
           "--allowedTools", "mcp__bot-ops-demo__*", "--output-format", "stream-json", "--verbose",
           "--tools", ""]  # no built-in tools: without this it can open the demo data files directly
    if model:
        cmd += ["--model", model]
    out = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=900).stdout
    calls, texts, pending = [], [], {}
    for line in out.splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("type") == "assistant":
            for b in e["message"]["content"]:
                if b["type"] == "tool_use" and b["name"].startswith("mcp__bot-ops-demo__"):
                    pending[b["id"]] = {"name": b["name"].rsplit("__", 1)[-1], "args": b["input"]}
                elif b["type"] == "text":
                    texts.append(b["text"])
        elif e.get("type") == "user":
            for b in e["message"]["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    c = b["content"]
                    pending[b["tool_use_id"]]["result"] = c if isinstance(c, str) else "".join(x.get("text", "") for x in c)
                    calls.append(pending.pop(b["tool_use_id"]))
        elif e.get("type") == "result":
            return {"answer": "\n\n".join(texts), "calls": calls, "error": None if e.get("subtype") == "success" else e.get("subtype")}
    return {"answer": "\n\n".join(texts), "calls": calls, "error": "no result event"}


def ask(agent: str, question: str) -> dict:
    t0 = time.time()
    try:
        if agent.startswith("ollama:"):
            out = asyncio.run(_run_ollama(agent.split(":", 1)[1], question))
        elif agent == "claude" or agent.startswith("claude:"):
            out = _run_claude(question, agent.split(":", 1)[1] if ":" in agent else None)
        else:
            raise ValueError(f"unknown agent {agent}")
    except Exception as e:
        out = {"answer": "", "calls": [], "error": f"{type(e).__name__}: {e}"}
    out.setdefault("error", None)
    out["seconds"] = round(time.time() - t0, 1)
    return out
