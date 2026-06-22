"""Sunshine · organ: reason — the main model + retrieval-hijack.

The scarce, slow tier. Run sparingly, never on raw input. Hijacked by clean recalled lessons (Law 1)
and verbosity-controlled by the model's native thinking toggle — NO budget/prime hacks (those were
Nanbeige workarounds; Qwen3.5 has enable_thinking). The worker, not this, formats the output (Law 2):
reason() returns an INTENT (a literal command / a plain answer); the fast organ turns it into a call.

POST /reason {problem, lessons?[], recall_ns?, recall_k?, effort=normal, want=answer}
  -> {conclusion, reasoning, effort, tokens, hijacked}
effort: terse (thinking off, ~200 tok) | normal (thinking off, ~1200 tok) | deep (thinking on, full)
want:   answer (the conclusion text) | command (extract the next shell command)
"""
import os, json, re, urllib.request
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List

MAIN_URL = os.getenv("MAIN_URL", "http://127.0.0.1:8072/v1/chat/completions")
MAIN_MODEL = os.getenv("MAIN_MODEL", "qwen3.5-4b")
MEMORY_URL = os.getenv("MEMORY_URL", "")            # optional: reason can recall its own lessons
app = FastAPI(title="sunshine-reason")

EFFORT = {"terse": (False, 256), "normal": (False, 1400), "deep": (True, 6000)}
_SKIP = ("-", "#", "*", "let", "i ", "the ", "now", "next", "first", "then", "so ", "we ", "wait", "but", "another", "however")


def _looks_like_cmd(s):
    if not s or len(s) < 2 or len(s) > 300 or s.endswith(":") or s[0] in "{}[]\"" or '": "' in s:
        return False
    return not s.lower().startswith(_SKIP)


def _extract_command(text):
    if "ACTION:" in text:
        c = text.rsplit("ACTION:", 1)[-1].strip().splitlines()[0].strip()
        if _looks_like_cmd(c):
            return c
    m = re.search(r"```(?:bash|sh)?\s*\n?(.+?)```", text, re.S)
    if m and _looks_like_cmd(m.group(1).strip().splitlines()[0].strip()):
        return m.group(1).strip().splitlines()[0].strip()
    for ln in reversed(text.strip().splitlines()):
        s = ln.strip().lstrip("$ ").strip("`").strip()
        if _looks_like_cmd(s):
            return s
    return text.strip().splitlines()[-1].strip() if text.strip() else ""


def _recall(ns, q, k):
    try:
        r = urllib.request.Request(MEMORY_URL.rstrip("/") + "/recall",
                                   data=json.dumps({"ns": ns, "q": q, "k": k}).encode(),
                                   headers={"Content-Type": "application/json"})
        return [h["value"] for h in json.loads(urllib.request.urlopen(r, timeout=15).read()).get("hits", [])]
    except Exception:
        return []


def _hijack_msg(lessons):
    body = "  ".join(f"I recall a relevant case — {l.strip()}" for l in lessons[:3])
    return ("[Relevant experience] " + body + "  Those were OTHER tasks; reuse the general APPROACH but use "
            "values correct for THIS task, not their specific paths/hosts/URLs.")


def _call(messages, thinking, max_tokens, prefill=None):
    """prefill (the <think> hijack) continues the assistant's OWN thought — the model owns the recalled
    reasoning (steers better than an advisory message; the Nanbeige finding, restored for Qwen)."""
    body = {"model": MAIN_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.6,
            "top_p": 0.95, "chat_template_kwargs": {"enable_thinking": thinking}}
    if prefill is not None:
        body["messages"] = messages + [{"role": "assistant", "content": prefill}]
        body["continue_final_message"] = True; body["add_generation_prompt"] = False
    r = urllib.request.Request(MAIN_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(r, timeout=200).read())
    out = d["choices"][0]["message"].get("content") or ""
    return ((prefill + out) if prefill else out), d["usage"]["completion_tokens"]


def _think_prefill(lessons):
    body = "  ".join(f"I recall a relevant case — {l.strip()}" for l in lessons[:3])
    return ("<think>\n" + body + "  Those were OTHER tasks; I'll reuse the general APPROACH but use "
            "values correct for THIS task, not their specific paths/hosts/URLs.\n")


class ReasonReq(BaseModel):
    problem: str
    lessons: Optional[List[str]] = None
    recall_ns: Optional[str] = None
    recall_k: int = 2
    effort: str = "normal"
    want: str = "answer"                             # answer | command


@app.get("/health")
def health(): return {"status": "ok", "main": MAIN_MODEL}


@app.post("/reason")
def reason(req: ReasonReq):
    thinking, mx = EFFORT.get(req.effort, EFFORT["normal"])
    lessons = req.lessons or (_recall(req.recall_ns, req.problem, req.recall_k) if (req.recall_ns and MEMORY_URL) else [])
    sysp = ("You are a capable problem-solver. Reason about the task" +
            (", then end with one line `ACTION: <the single exact shell command to run next>`."
             if req.want == "command" else " and give a clear, correct answer."))
    msgs = [{"role": "system", "content": sysp}, {"role": "user", "content": req.problem}]
    if lessons:
        # HIJACK = inject the recalled lessons as an UNCLOSED <think> prefill (model owns the reasoning,
        # steers better than a message). enable_thinking on so the prefill continues a real thought.
        text, tok = _call(msgs, True, max(mx, 1400), prefill=_think_prefill(lessons))
    else:
        text, tok = _call(msgs, thinking, mx)
    answer = text.split("</think>")[-1].strip() if "</think>" in text else text.strip()
    conclusion = _extract_command(answer) if req.want == "command" else answer
    return {"conclusion": conclusion, "reasoning": (text if thinking else ""),
            "effort": req.effort, "tokens": tok, "hijacked": bool(lessons)}
