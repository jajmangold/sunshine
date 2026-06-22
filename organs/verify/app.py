"""Sunshine · organ: verify — the verifier bus (Law 3: verify, don't trust).

Cheap reward signals behind one API, so best-of-N is a substrate feature, not a special case.
kinds:
  wasm-python : run candidate Python in the Pyodide sandbox (optional test suffix) -> pass = no error/assert
  critic      : main model judges correctness (yes/no)
  vlm         : (stub) VLM-judge for studio — wire when a Sunshine vision model is deployed

POST /verify {candidate, kind, test?}                    -> {ok, detail}
POST /bestof {candidates, kind, test?}                   -> {winner, index, results}
"""
import os, json, urllib.request
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List

SANDBOX_URL = os.getenv("SANDBOX_URL", "http://172.30.0.2:8000/run")   # lm-stack wasm-sandbox (Pyodide)
MAIN_URL = os.getenv("MAIN_URL", "http://127.0.0.1:8072/v1/chat/completions")
MAIN_MODEL = os.getenv("MAIN_MODEL", "qwen3.5-4b")
app = FastAPI(title="sunshine-verify")


def _wasm(code, timeout_ms=6000):
    r = urllib.request.Request(SANDBOX_URL, data=json.dumps({"code": code, "timeout_ms": timeout_ms}).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())


def _critic(candidate):
    g = 'root ::= "{" ws "\\"correct\\":" ws ("true" | "false") ws "}"\nws ::= [ \\t\\n]?'
    body = {"model": MAIN_MODEL, "max_tokens": 600, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}, "structured_outputs": {"grammar": g},
            "messages": [{"role": "system", "content": "Judge whether the answer is correct. Output {\"correct\": true|false}."},
                         {"role": "user", "content": candidate[:2000]}]}
    try:
        r = urllib.request.Request(MAIN_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(r, timeout=120).read())["choices"][0]["message"]["content"]
        return bool(json.loads(out).get("correct"))
    except Exception:
        return False


def _verify_one(candidate, kind, test):
    if kind == "wasm-python":
        code = candidate + ("\n" + test if test else "")
        try:
            r = _wasm(code)
            return bool(r.get("ok") and not r.get("error")), {"stdout": (r.get("stdout") or "")[:300], "error": r.get("error")}
        except Exception as e:
            return False, {"error": str(e)[:120]}
    if kind == "critic":
        ok = _critic(candidate); return ok, {"verdict": ok}
    return False, {"error": f"unknown kind {kind}"}


class VerifyReq(BaseModel):
    candidate: str
    kind: str = "wasm-python"
    test: Optional[str] = None


class BestofReq(BaseModel):
    candidates: List[str]
    kind: str = "wasm-python"
    test: Optional[str] = None


@app.get("/health")
def health(): return {"status": "ok", "sandbox": SANDBOX_URL}


@app.post("/verify")
def verify(req: VerifyReq):
    ok, detail = _verify_one(req.candidate, req.kind, req.test)
    return {"ok": ok, "detail": detail}


@app.post("/bestof")
def bestof(req: BestofReq):
    with ThreadPoolExecutor(min(len(req.candidates), 8)) as ex:
        results = list(ex.map(lambda c: _verify_one(c, req.kind, req.test), req.candidates))
    for i, (ok, _) in enumerate(results):
        if ok:
            return {"winner": req.candidates[i], "index": i, "ok": True,
                    "results": [{"ok": o, "detail": d} for o, d in results]}
    return {"winner": None, "index": -1, "ok": False, "results": [{"ok": o, "detail": d} for o, d in results]}
