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


def _call(messages, grammar=None, schema=None, max_tokens=1024, thinking=False, temp=0.3):
    body = {"model": MAIN_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temp,
            "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": thinking}}
    if grammar:
        body["structured_outputs"] = {"grammar": grammar}
    elif schema:
        body["structured_outputs"] = {"json": schema}
    r = urllib.request.Request(MAIN_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(r, timeout=240).read())
    msg = d["choices"][0]["message"]
    txt = msg.get("content") or ""
    if "</think>" in txt:
        txt = txt.split("</think>")[-1].strip()
    return txt, d.get("usage", {})


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


def decide(msgs, tools):
    names = [_name_of(t) for t in tools]
    alt = " | ".join('"\\"' + n + '\\""' for n in names + ["respond"])
    grammar = ('root ::= "{" ws "\\"choice\\":" ws (' + alt + ') ws "}"\nws ::= [ \\t\\n]?')
    nudge = {"role": "user", "content": 'Output your next action as {"choice":"<' + "|".join(names + ["respond"]) + '>"}.'}
    txt, u = _call(msgs + [nudge], grammar=grammar, max_tokens=20, temp=0.0)
    try:
        return json.loads(txt).get("choice", "respond"), u
    except Exception:
        return "respond", u


def gen_args(msgs, tool):
    nudge = {"role": "user", "content": f"Call the tool `{_name_of(tool)}`. Produce ONLY its JSON arguments."}
    txt, u = _call(msgs + [nudge], schema=_schema_of(tool), max_tokens=1200)
    try:
        return json.loads(txt), u
    except Exception:
        return {}, u


def gen_text(msgs, thinking=True):
    return _call(msgs, max_tokens=1500, thinking=thinking)


def turn(msgs, tools):
    """Shared core -> ('text', content) | ('tool', name, args). msgs already normalized + tool-described."""
    if not tools:
        t, _ = gen_text(msgs)
        return ("text", t)
    choice, _ = decide(msgs, tools)
    if choice == "respond" or choice not in [_name_of(t) for t in tools]:
        t, _ = gen_text(msgs)
        return ("text", t)
    tool = next(t for t in tools if _name_of(t) == choice)
    args, _ = gen_args(msgs, tool)
    return ("tool", choice, args)


def _prep(messages, tools, system_top=None):
    msgs = normalize(messages, system_top)
    if tools:                                                # prepend blindness preamble + append tool list
        note = AGENT_PREAMBLE + "\n\n" + _tooldesc(tools)
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += "\n\n" + note
        else:
            msgs = [{"role": "system", "content": note}] + msgs
    return msgs


# ---------------- OpenAI surface ----------------
def _openai_resp(result, model):
    cid = "chatcmpl-" + uuid.uuid4().hex[:24]
    base = {"id": cid, "object": "chat.completion", "created": int(time.time()), "model": model,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
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
    msgs = _prep(body.get("messages", []), tools)
    resp = _openai_resp(turn(msgs, tools), body.get("model", MODEL_ID))
    if body.get("stream"):
        return StreamingResponse(_openai_sse(resp), media_type="text/event-stream")
    return JSONResponse(resp)


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "sunshine"}]}


# ---------------- Anthropic surface ----------------
def _anthropic_resp(result, model):
    if result[0] == "tool":
        content = [{"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:20], "name": result[1], "input": result[2]}]
        stop = "tool_use"
    else:
        content = [{"type": "text", "text": result[1]}]; stop = "end_turn"
    return {"id": "msg_" + uuid.uuid4().hex[:20], "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}


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
    msgs = _prep(body.get("messages", []), tools, system_top=body.get("system"))
    resp = _anthropic_resp(turn(msgs, tools), body.get("model", MODEL_ID))
    if body.get("stream"):
        return StreamingResponse(_anthropic_sse(resp), media_type="text/event-stream")
    return JSONResponse(resp)


@app.get("/health")
def health():
    return {"status": "ok", "model": MAIN_MODEL, "surfaces": ["openai:/v1/chat/completions", "anthropic:/v1/messages"]}
