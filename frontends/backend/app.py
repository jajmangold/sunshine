"""Sunshine · backend — faithful OpenAI + Anthropic passthrough for opencode / pi / Codex (issue #13).

Be a real model: full messages + tools in -> native tool_calls / tool_use out, stateless. Tool-calling is
OURS (no native parser): the model decides which tool over full context (grammar enum), then the args are
generated under that tool's JSON schema (guaranteed-valid). The shim assembles the protocol response.
Streaming = buffered SSE (compute fully, emit one chunk + [DONE]). Augmentation (repo-map, etc.) layers in
later as an appended system note — invisible to the harness.

  POST /v1/chat/completions   (OpenAI)        POST /v1/messages   (Anthropic)
  GET  /v1/models                             GET  /health
"""
import os, json, time, uuid, urllib.request
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MAIN_URL = os.getenv("MAIN_URL", "http://127.0.0.1:8072/v1/chat/completions")
MAIN_MODEL = os.getenv("MAIN_MODEL", "qwen3.5-4b")
MODEL_ID = os.getenv("MODEL_ID", "sunshine")
app = FastAPI(title="sunshine-backend")

_STR = ('str ::= "\\"" schar* "\\""\n'
        'schar ::= [^"\\\\\\n\\r\\t] | "\\\\" ["\\\\/bfnrt]\n'
        'ws ::= [ \\t\\n]?')


# the model must know it's BLIND without tools, or it answers env questions from imagination
AGENT_PREAMBLE = ("You are an autonomous coding agent. You are BLIND to this environment — you cannot see "
                  "files, directory contents, command output, or code unless you obtain it by calling a tool. "
                  "If answering correctly depends on the actual files/commands/code here, you MUST call a tool; "
                  "respond directly only for general knowledge or conversation needing no environment access.")


MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8090")
REASON_NS = os.getenv("SUN_REASON_NS", "agent-traces,recipes,eval-lessons").split(",")


def _call(messages, grammar=None, schema=None, max_tokens=1024, thinking=False, temp=0.3, prefill=None):
    body = {"model": MAIN_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temp,
            "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": thinking}}
    if grammar:
        body["structured_outputs"] = {"grammar": grammar}
    elif schema:
        body["structured_outputs"] = {"json": schema}
    if prefill is not None:                                  # the <think> hijack: model OWNS the recalled reasoning
        body["messages"] = messages + [{"role": "assistant", "content": prefill}]
        body["continue_final_message"] = True; body["add_generation_prompt"] = False
    r = urllib.request.Request(MAIN_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(r, timeout=240).read())
    msg = d["choices"][0]["message"]
    txt = msg.get("content") or ""
    if "</think>" in txt:
        txt = txt.split("</think>")[-1].strip()
    return txt, d.get("usage", {})


def recall_reasoning(query, k=2, min_sim=0.62):
    """Retrieve relevant REASONING TRACES/approaches (not just facts) to hijack the model's thought."""
    try:
        r = urllib.request.Request(MEMORY_URL.rstrip("/") + "/recall",
            data=json.dumps({"ns": REASON_NS, "q": query[-1500:],
                             "k": k, "min_sim": min_sim}).encode(), headers={"Content-Type": "application/json"})
        return [h["value"] for h in json.loads(urllib.request.urlopen(r, timeout=12).read()).get("hits", [])]
    except Exception:
        return []


def _reason_prefill(traces):
    """Recalled reasoning as the model's OWN unclosed thought (the retrieval-hijack; Nanbeige core)."""
    body = "  ".join(f"I recall a similar case — {t.strip()}" for t in traces[:2])
    return ("<think>\n" + body + "  That was another situation; I'll reuse the APPROACH here with the right "
            "values for THIS task. Let me reason out the single best next action.\n")


# ---- faithful transcript: flatten ANY harness's messages into clean role+text the model reads ----
def _blocks_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        t = b.get("type")
        if t == "text":
            parts.append(b.get("text", ""))
        elif t == "tool_use":
            parts.append(f"[called {b.get('name')}({json.dumps(b.get('input', {}))})]")
        elif t == "tool_result":
            c = b.get("content")
            parts.append("[tool result] " + (c if isinstance(c, str) else _blocks_text(c)))
    return "\n".join(parts)


def normalize(messages, system_top=None):
    """-> [{role, content}] for the model. tool/assistant-tool-calls/results become readable text."""
    out = []
    if system_top:
        out.append({"role": "system", "content": system_top if isinstance(system_top, str) else _blocks_text(system_top)})
    for m in messages:
        role = m.get("role", "user")
        if role == "tool":                                   # OpenAI tool result
            out.append({"role": "user", "content": "[tool result] " + str(m.get("content", ""))})
            continue
        txt = _blocks_text(m.get("content"))
        if role == "assistant" and m.get("tool_calls"):      # OpenAI assistant tool call
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                txt += f"\n[called {fn.get('name')}({fn.get('arguments', '')})]"
        out.append({"role": role, "content": txt or ""})
    # merge any non-leading system messages into the first (Qwen: one system, first)
    sys_parts = [m["content"] for m in out if m["role"] == "system"]
    rest = [m for m in out if m["role"] != "user" or True]
    body = [m for m in out if m["role"] != "system"]
    head = [{"role": "system", "content": "\n\n".join(sys_parts)}] if sys_parts else []
    return head + body


def _tooldesc(tools):
    lines = []
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "")
        desc = (fn.get("description", "") or "")[:200]
        lines.append(f"- {name}: {desc}")
    return "Available tools:\n" + "\n".join(lines)


def _schema_of(tool):
    fn = tool.get("function", tool)
    return fn.get("parameters") or fn.get("input_schema") or {"type": "object", "properties": {}}


def _name_of(tool):
    return tool.get("function", tool).get("name", "")


def _action_schema(tools):
    """oneOf: emit a tool-with-its-exact-args, or a respond — ONE constrained call (vs two-phase)."""
    branches = []
    for t in tools:
        branches.append({"type": "object", "additionalProperties": False, "required": ["tool", "args"],
                         "properties": {"tool": {"const": _name_of(t)}, "args": _schema_of(t)}})
    branches.append({"type": "object", "additionalProperties": False, "required": ["respond"],
                     "properties": {"respond": {"type": "string"}}})
    return {"oneOf": branches}


def _sig(name, args):
    try:
        return name + json.dumps(args, sort_keys=True)
    except Exception:
        return name + str(args)


def gen_text(msgs, thinking=True):
    return _call(msgs, max_tokens=1500, thinking=thinking)


def turn(msgs, tools, recent_sigs=(), loop_detect=False, reason_traces=None):
    """Shared core -> (('text',content)|('tool',name,args), tokens). Single constrained call —
    but if reasoning traces are recalled, FIRST hijack the model's thought with them (it owns the
    reasoning), THEN emit the grammar action informed by that reasoning. (Grammar can't co-exist with
    open-think in one call, so reasoning-injection is two-phase: reason-with-prefill -> grammar-act.)"""
    tok = 0
    if reason_traces:                                        # REASONING-INJECTION (the retrieval-hijack)
        rmsgs = msgs + [{"role": "user", "content": "Reason out the single best next action for this task."}]
        reasoning, ru = _call(rmsgs, max_tokens=500, thinking=True, prefill=_reason_prefill(reason_traces))
        tok += ru.get("completion_tokens", 0)
        # the trace content lives in the (stripped) <think>; carry BOTH the recalled approach AND the
        # model's own continuation into the action phase, else the injected reasoning evaporates.
        ctx = "[Recalled approach] " + "  ".join(t.strip()[:320] for t in reason_traces[:2])
        if reasoning.strip():
            ctx += "\n[My reasoning] " + reasoning.strip()[-400:]
        msgs = msgs + [{"role": "user", "content": ctx}]
    if not tools:
        t, u = gen_text(msgs)
        return ("text", t), tok + u.get("completion_tokens", 0)
    schema = _action_schema(tools)
    names = [_name_of(t) for t in tools]
    nudge = {"role": "user", "content": 'Take your next action: call a tool as {"tool":<name>,"args":{...}} '
             'or answer as {"respond":"..."}.'}
    txt, u = _call(msgs + [nudge], schema=schema, max_tokens=1500, temp=0.2)
    tok += u.get("completion_tokens", 0)
    try:
        obj = json.loads(txt)
    except Exception:
        return ("text", txt), tok
    if "tool" in obj and obj["tool"] in names:
        name, args = obj["tool"], obj.get("args", {})
        if loop_detect and _sig(name, args) in recent_sigs:           # RUNG: escape repeats
            anti = {"role": "user", "content": f"You ALREADY ran {name} with those args and it did not help. "
                    "Do something genuinely DIFFERENT — diagnose why, or try another approach."}
            txt2, u2 = _call(msgs + [anti, nudge], schema=schema, max_tokens=1500, temp=0.5, thinking=False)
            tok += u2.get("completion_tokens", 0)
            try:
                o2 = json.loads(txt2)
                if "tool" in o2 and o2["tool"] in names:
                    return ("tool", o2["tool"], o2.get("args", {})), tok
                return ("text", o2.get("respond", "")), tok
            except Exception:
                pass
        return ("tool", name, args), tok
    return ("text", obj.get("respond", txt)), tok


def _recent_sigs_openai(messages, k=3):
    sigs = []
    for m in messages:
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {})
                try:
                    a = json.loads(fn.get("arguments", "{}") or "{}")
                except Exception:
                    a = {}
                sigs.append(_sig(fn.get("name", ""), a))
    return sigs[-k:]


def _recent_sigs_anthropic(messages, k=3):
    sigs = []
    for m in messages:
        for b in (m.get("content") or []) if isinstance(m.get("content"), list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                sigs.append(_sig(b.get("name", ""), b.get("input", {})))
    return sigs[-k:]


def _prep(messages, tools, system_top=None, recall_note=None):
    msgs = normalize(messages, system_top)
    add = ""
    if tools:                                                # blindness preamble + tool list
        add += "\n\n" + AGENT_PREAMBLE + "\n\n" + _tooldesc(tools)
    if recall_note:                                          # recalled experience as a NOTE (measured-best for facts)
        add += "\n\n[Relevant experience — apply the approach/values if useful]\n" + recall_note
    if add:
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += add
        else:
            msgs = [{"role": "system", "content": add.strip()}] + msgs
    return msgs


# ---------------- OpenAI surface ----------------
def _openai_resp(result, model, tokens=0):
    cid = "chatcmpl-" + uuid.uuid4().hex[:24]
    base = {"id": cid, "object": "chat.completion", "created": int(time.time()), "model": model,
            "usage": {"prompt_tokens": 0, "completion_tokens": tokens, "total_tokens": tokens}}
    if result[0] == "tool":
        msg = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_" + uuid.uuid4().hex[:20], "type": "function",
            "function": {"name": result[1], "arguments": json.dumps(result[2])}}]}
        fin = "tool_calls"
    else:
        msg = {"role": "assistant", "content": result[1]}; fin = "stop"
    base["choices"] = [{"index": 0, "message": msg, "finish_reason": fin}]
    return base


def _openai_sse(resp):
    cid, model, created = resp["id"], resp["model"], resp["created"]
    msg = resp["choices"][0]["message"]; fin = resp["choices"][0]["finish_reason"]
    delta = {"role": "assistant"}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{"index": 0, **msg["tool_calls"][0]}]
    else:
        delta["content"] = msg.get("content") or ""
    chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
             "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
    yield f"data: {json.dumps(chunk)}\n\n"
    done = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": fin}]}
    yield f"data: {json.dumps(done)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def openai_chat(req: Request):
    body = await req.json()
    tools = body.get("tools") or []
    ld = req.headers.get("x-sun-loopdetect", "on").lower() not in ("off", "0", "false")
    # MEASURED: deliver recalled experience as a NOTE by default (works for facts); the <think> HIJACK
    # corrupts precise facts (it grabbed a hash over the key) -> hijack is OPT-IN (x-sun-reason:on) for steering.
    hijack = req.headers.get("x-sun-reason", "off").lower() in ("on", "1", "true")
    rc = req.headers.get("x-sun-recall", "on").lower() not in ("off", "0", "false")
    recent = _recent_sigs_openai(body.get("messages", []))
    traces = note = None
    if rc or hijack:
        users = [m["content"] for m in body.get("messages", []) if m.get("role") == "user" and isinstance(m.get("content"), str)]
        traces = recall_reasoning((users[0] if users else "") + "  " + (users[-1] if len(users) > 1 else "")) or None
        if traces and rc:
            note = "\n".join("- " + t for t in traces)
    msgs = _prep(body.get("messages", []), tools, recall_note=note)
    result, tok = turn(msgs, tools, recent, ld, traces if hijack else None)
    resp = _openai_resp(result, body.get("model", MODEL_ID), tok)
    if body.get("stream"):
        return StreamingResponse(_openai_sse(resp), media_type="text/event-stream")
    return JSONResponse(resp)


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "sunshine"}]}


# ---------------- Anthropic surface ----------------
def _anthropic_resp(result, model, tokens=0):
    if result[0] == "tool":
        content = [{"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:20], "name": result[1], "input": result[2]}]
        stop = "tool_use"
    else:
        content = [{"type": "text", "text": result[1]}]; stop = "end_turn"
    return {"id": "msg_" + uuid.uuid4().hex[:20], "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": tokens}}


def _anthropic_sse(resp):
    mid, model = resp["id"], resp["model"]
    blk = resp["content"][0]
    start = {"type": "message_start", "message": {**resp, "content": []}}
    yield f"event: message_start\ndata: {json.dumps(start)}\n\n"
    if blk["type"] == "tool_use":
        cbs = {"type": "content_block_start", "index": 0,
               "content_block": {"type": "tool_use", "id": blk["id"], "name": blk["name"], "input": {}}}
        yield f"event: content_block_start\ndata: {json.dumps(cbs)}\n\n"
        d = {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": json.dumps(blk["input"])}}
        yield f"event: content_block_delta\ndata: {json.dumps(d)}\n\n"
    else:
        cbs = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
        yield f"event: content_block_start\ndata: {json.dumps(cbs)}\n\n"
        d = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": blk["text"]}}
        yield f"event: content_block_delta\ndata: {json.dumps(d)}\n\n"
    yield f"event: content_block_stop\ndata: {json.dumps({'type':'content_block_stop','index':0})}\n\n"
    md = {"type": "message_delta", "delta": {"stop_reason": resp["stop_reason"]}, "usage": {"output_tokens": 0}}
    yield f"event: message_delta\ndata: {json.dumps(md)}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type':'message_stop'})}\n\n"


@app.post("/v1/messages")
async def anthropic_messages(req: Request):
    body = await req.json()
    tools = body.get("tools") or []
    ld = req.headers.get("x-sun-loopdetect", "on").lower() not in ("off", "0", "false")
    hijack = req.headers.get("x-sun-reason", "off").lower() in ("on", "1", "true")
    rc = req.headers.get("x-sun-recall", "on").lower() not in ("off", "0", "false")
    recent = _recent_sigs_anthropic(body.get("messages", []))
    traces = note = None
    if rc or hijack:
        users = [_blocks_text(m.get("content")) for m in body.get("messages", []) if m.get("role") == "user"]
        traces = recall_reasoning((users[0] if users else "") + "  " + (users[-1] if len(users) > 1 else "")) or None
        if traces and rc:
            note = "\n".join("- " + t for t in traces)
    msgs = _prep(body.get("messages", []), tools, system_top=body.get("system"), recall_note=note)
    result, tok = turn(msgs, tools, recent, ld, traces if hijack else None)
    resp = _anthropic_resp(result, body.get("model", MODEL_ID), tok)
    if body.get("stream"):
        return StreamingResponse(_anthropic_sse(resp), media_type="text/event-stream")
    return JSONResponse(resp)


@app.get("/health")
def health():
    return {"status": "ok", "model": MAIN_MODEL, "surfaces": ["openai:/v1/chat/completions", "anthropic:/v1/messages"]}
