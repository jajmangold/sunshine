"""Sunshine · output-shaper — define the output SHAPE first, generate through it (issue #14).

Small models fail at FORMAT, not content. ROUTE the ask to an output type, retrieve/author its
grammar-or-schema (the `templates` library, define-as-you-go), generate THROUGH it (schema-constrained
decode), and for code: the structured-EDIT shape doubles as the verify contract (apply -> diff -> test).

Templates registry seeds the `templates` memory namespace; new shapes get authored + cached.

POST /shape  {output_type, intent, file?, file_content?, schema?}  -> the shaped object (schema-valid)
POST /apply  {file_content, edits:[{old,new}]}                     -> {new_content, applied, failed, diff}
GET  /templates                                                    -> known output shapes
"""
import os, json, difflib, urllib.request
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Any

MAIN_URL = os.getenv("MAIN_URL", "http://127.0.0.1:8072/v1/chat/completions")
MAIN_MODEL = os.getenv("MAIN_MODEL", "qwen3.5-4b")
app = FastAPI(title="sunshine-shaper")

# --- the templates library (seed). kind: json_schema (constrained decode) | jinja (slot-fill). ---
# Structured-EDIT: search/replace blocks. NEVER a raw-diff grammar (diffs depend on file content).
EDIT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "file": {"type": "string"},
        "edits": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
            "required": ["old", "new"]}},
    }, "required": ["file", "edits"]}

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
    "required": ["steps"]}

TEMPLATES = {
    "structured_edit": {"kind": "json_schema", "schema": EDIT_SCHEMA,
                        "system": "Make the requested change by emitting search/replace edits. Each `old` "
                                  "must be the EXACT text currently in the file (enough lines to be unique); "
                                  "`new` is its replacement. Do not restate the whole file."},
    "plan": {"kind": "json_schema", "schema": PLAN_SCHEMA,
             "system": "Break the task into an ordered list of concrete steps."},
}


def _gen(system, user, schema):
    body = {"model": MAIN_MODEL, "max_tokens": 1500, "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
            "structured_outputs": {"json": schema},   # vLLM structured_outputs JSON-schema key is `json`
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = urllib.request.Request(MAIN_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(r, timeout=180).read())["choices"][0]["message"]["content"]
    return json.loads(out)


def apply_edits(content, edits):
    """Apply search/replace edits. old must appear EXACTLY once. Returns (new, applied, failed)."""
    new, applied, failed = content, 0, []
    for i, e in enumerate(edits):
        old, repl = e.get("old", ""), e.get("new", "")
        cnt = new.count(old)
        if old and cnt == 1:
            new = new.replace(old, repl); applied += 1
        else:
            failed.append({"index": i, "reason": "not found" if cnt == 0 else f"{cnt} matches (ambiguous)",
                           "old": old[:80]})
    return new, applied, failed


class ShapeReq(BaseModel):
    output_type: str = "structured_edit"
    intent: str
    file: Optional[str] = None
    file_content: Optional[str] = None
    schema_: Optional[Any] = None                    # caller-supplied shape (e.g. a harness tool schema)


class ApplyReq(BaseModel):
    file_content: str
    edits: List[dict]


@app.get("/health")
def health(): return {"status": "ok", "templates": list(TEMPLATES)}


@app.get("/templates")
def templates(): return TEMPLATES


@app.post("/shape")
def shape(req: ShapeReq):
    tpl = TEMPLATES.get(req.output_type)
    schema = req.schema_ or (tpl and tpl["schema"])
    system = (tpl["system"] if tpl else "Produce the requested structured output.")
    if not schema:
        return {"error": f"no template for output_type '{req.output_type}' and no schema given"}
    user = req.intent + (f"\n\nFILE {req.file or ''}:\n{req.file_content}" if req.file_content else "")
    try:
        obj = _gen(system, user, schema)
    except Exception as e:
        return {"error": str(e)[:160]}
    res = {"output_type": req.output_type, "shaped": obj}
    if req.output_type == "structured_edit" and req.file_content is not None:   # the verify contract
        new, applied, failed = apply_edits(req.file_content, obj.get("edits", []))
        diff = "".join(difflib.unified_diff(req.file_content.splitlines(True), new.splitlines(True),
                                            "a/" + (obj.get("file") or "f"), "b/" + (obj.get("file") or "f")))
        res.update({"applied": applied, "failed": failed, "diff": diff, "ok": applied > 0 and not failed})
    return res


@app.post("/apply")
def apply(req: ApplyReq):
    new, applied, failed = apply_edits(req.file_content, req.edits)
    diff = "".join(difflib.unified_diff(req.file_content.splitlines(True), new.splitlines(True), "a", "b"))
    return {"new_content": new, "applied": applied, "failed": failed, "diff": diff, "ok": applied > 0 and not failed}
