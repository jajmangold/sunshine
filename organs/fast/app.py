"""Sunshine · organ: fast — the tiny-worker gateway.

One grammar-typed endpoint for the four fast-tier ops (ROUTE/DISTILL/ACT/JUDGE), backed by the worker
model (Qwen3.5-0.8B) at WORKER_URL. Law 2 (worker formats/judges, never reasons) + Law 3 (grammar =
guaranteed-valid output). Swarmable: n>1 runs the worker swarm and votes — cheap at ~2000 tok/s batched.

Replaces the per-site worker glue (reason-engine / websearch-digest / proxy / owui-tools) and kills the
parse/repair hand-fixes (the grammar guarantees structure).

POST /fast {op, system?, input, grammar?|grammar_name?|options?, n=1, vote, max_tokens, temperature}
  -> {result, raw, n, votes?}
"""
import os, json, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Any

WORKER_URL = os.getenv("WORKER_URL", "http://127.0.0.1:8071/v1/chat/completions")
WORKER_MODEL = os.getenv("WORKER_MODEL", "qwen3.5-0.8b")
app = FastAPI(title="sunshine-fast")

# ---- reusable grammar library (xgrammar GBNF; str/ws tail shared) ----
_TAIL = ('str ::= "\\"" schar* "\\""\n'
         'schar ::= [^"\\\\\\n\\r\\t] | "\\\\" ["\\\\/bfnrt]\n'
         'ws ::= [ \\t\\n]?')


def g_enum(options):                                 # ROUTE: pick exactly one option
    alt = " | ".join('"\\"' + o.replace('"', '') + '\\""' for o in options)
    return 'root ::= "{" ws "\\"choice\\":" ws (' + alt + ') ws "}"\nws ::= [ \\t\\n]?'


def g_bool():                                        # JUDGE: {"verdict": true|false}
    return 'root ::= "{" ws "\\"verdict\\":" ws ("true" | "false") ws "}"\nws ::= [ \\t\\n]?'


def g_toolcall(names):                               # ACT: pick a tool + command string
    alt = " | ".join('"\\"' + n + '\\""' for n in names)
    return ('root ::= "{" ws "\\"tool\\":" ws (' + alt + ') ws "," ws "\\"command\\":" ws str ws "}"\n' + _TAIL)


GRAMMARS = {"bool": g_bool}


def _call(system, user, grammar, max_tokens, temp):
    body = {"model": WORKER_MODEL, "temperature": temp, "max_tokens": max_tokens,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]}
    if grammar:
        body["structured_outputs"] = {"grammar": grammar}
    r = urllib.request.Request(WORKER_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())["choices"][0]["message"]["content"]


class FastReq(BaseModel):
    op: str                                          # route | distill | act | judge
    input: str
    system: Optional[str] = None
    grammar: Optional[str] = None
    grammar_name: Optional[str] = None
    options: Optional[List[str]] = None              # route/act(tool) enum
    n: int = 1
    vote: str = "majority"                           # majority | best
    max_tokens: int = 256
    temperature: float = 0.2


def _resolve(req: FastReq):
    """(grammar, default_system, parse_fn) for the op."""
    if req.op == "route":
        return g_enum(req.options or ["yes", "no"]), (req.system or "Choose the single best option."), \
            (lambda s: json.loads(s).get("choice"))
    if req.op == "judge":
        return g_bool(), (req.system or "Answer with a strict verdict."), (lambda s: json.loads(s).get("verdict"))
    if req.op == "act":
        if req.options:                              # tool-call act
            return g_toolcall(req.options), (req.system or "Emit the tool call."), (lambda s: json.loads(s))
        g = req.grammar or (GRAMMARS[req.grammar_name]() if req.grammar_name in GRAMMARS else None)
        return g, req.system, (lambda s: json.loads(s) if g else s)
    # distill: free-form condense (no grammar by default)
    return req.grammar, (req.system or "Distill into ONE clean generic lesson, omit specifics."), (lambda s: s.strip())


@app.get("/health")
def health(): return {"status": "ok", "worker": WORKER_MODEL}


@app.post("/fast")
def fast(req: FastReq):
    grammar, system, parse = _resolve(req)
    def one(_):
        try:
            return parse(_call(system, req.input, grammar, req.max_tokens, req.temperature))
        except Exception:
            return None
    if req.n <= 1:
        return {"result": one(0), "n": 1}
    with ThreadPoolExecutor(min(req.n, 32)) as ex:
        results = [r for r in ex.map(one, range(req.n)) if r is not None]
    if not results:
        return {"result": None, "n": req.n, "votes": {}}
    if req.vote == "majority":                       # vote on hashable results (route/judge)
        try:
            tally = Counter(json.dumps(r, sort_keys=True) if not isinstance(r, (str, bool, int)) else r for r in results)
            winner, votes = tally.most_common(1)[0]
            win = next(r for r in results if (json.dumps(r, sort_keys=True) if not isinstance(r, (str, bool, int)) else r) == winner)
            return {"result": win, "n": req.n, "votes": dict(tally)}
        except Exception:
            pass
    return {"result": results[0], "n": req.n, "all": results}
