"""The assistants under test. Each takes a question and returns
{"answer": str, "calls": [{"name", "args", "result"}], "seconds": float, "error": str | None}.

  ollama:<model>   a local model in a plain tool-calling loop against the demo server (in-process MCP client).
                   It gets the server's own instructions as the system prompt, like an MCP host would pass them.
  claude           Claude Code in headless mode (`claude -p`) with only the demo server connected.

[한국어] 시험받는 어시스턴트들. 각각 질문 하나를 받아 위 모양의 dict(answer, calls, seconds, error)를 돌려준다.
ollama:<model>은 로컬 모델이다. 데모 서버에 붙여 단순한 도구 호출 루프로 돌린다(같은 프로세스 안의 MCP 클라이언트).
MCP 호스트가 넘기듯 서버의 instructions를 시스템 프롬프트로 받는다.
claude는 Claude Code를 headless 모드(`claude -p`)로 돌린다. 데모 서버만 연결한다.
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
os.environ["BOT_OPS_DEMO"] = "1"  # before bot_ops is imported / bot_ops를 import하기 전에 둔다
sys.path.insert(0, str(ROOT))

from mcp.client.client import Client  # noqa: E402

from bot_ops.server import mcp as server  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_HOST", "localhost:11434")
OLLAMA = OLLAMA if OLLAMA.startswith("http") else "http://" + OLLAMA  # the env var is often set without a scheme / 이 환경 변수는 scheme(http://) 없이 설정된 경우가 많다
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
                        # memory-mapping을 끈다. 켜 두면 가중치가 GPU에 있는 동안에도 RAM에 같이 남는다.
                        # 그래서 16 GB VRAM에 다 안 들어가는 모델이 32 GB 컴퓨터의 메모리를 다 써 버렸다(2026-10-10)
                        "use_mmap": False}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def _ollama_loaded(model: str) -> dict:
    """Model size and how much of it sits in GPU memory, from /api/ps (the model is still loaded after a run).

    [한국어] 모델 크기와 그중 GPU 메모리에 올라간 비율. /api/ps에서 읽는다(실행이 끝나도 모델은 아직 올라가 있다).
    """
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
                except Exception as e:  # unknown tool, bad arguments: tell the model, like a host would / 없는 도구, 잘못된 인자: 호스트가 하듯 모델에게 알려 준다
                    text = json.dumps({"error": f"{type(e).__name__}: {e}"})
                calls.append({"name": name, "args": args, "result": text})
                messages.append({"role": "tool", "tool_name": name, "content": text})
        return {"answer": "", "calls": calls, "error": f"no final answer after {MAX_STEPS} steps",
                "stats": {**st, **_ollama_loaded(model)}}


def _run_claude(question: str, model: str | None = None) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]  # demo/mcp.json runs `python` / demo/mcp.json이 `python`을 실행한다
    cmd = ["claude", "-p", question, "--mcp-config", "demo/mcp.json", "--strict-mcp-config",
           "--allowedTools", "mcp__bot-ops-demo__*", "--output-format", "stream-json", "--verbose",
           "--tools", ""]  # no built-in tools: without this it can open the demo data files directly / 내장 도구를 뺀다. 안 빼면 데모 데이터 파일을 직접 열어 볼 수 있다
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
