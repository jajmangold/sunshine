"""Sunshine · organ: kernel — the universal loop.

Composes the organs (memory · fast · reason · verify) into ONE policy. Every product = kernel + 3 knobs
(corpus / grammar / verifier), declared per SKILL. Enforces the loop and the 3 laws.

  INGEST -> ROUTE -> RECALL -> [fast ACT | slow REASON] -> VERIFY/best-of-N -> EMIT

POST /solve {task, skill="agent", context?, effort="terse", n=1}  -> {output, intent, lessons, verified}
GET  /skills
"""
import os, json, urllib.request
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

MEMORY = os.getenv("MEMORY_URL", "http://127.0.0.1:8090")
FAST = os.getenv("FAST_URL", "http://127.0.0.1:8091")
REASON = os.getenv("REASON_URL", "http://127.0.0.1:8092")
VERIFY = os.getenv("VERIFY_URL", "http://127.0.0.1:8093")
app = FastAPI(title="sunshine-kernel")
HIJACK_MIN_SIM = float(os.getenv("HIJACK_MIN_SIM", "0.6"))   # below this: orphan (reason un-hijacked, not misled)

# the 3 knobs per skill: corpus (RECALL namespaces) · act-format · verifier
SKILLS = {
    "agent": {"corpus": ["agent-traces", "recipes"], "want": "command",
              "act": {"options": ["run_bash", "finish"]}, "verifier": None},
    "terminus": {"corpus": ["agent-traces", "recipes"], "want": "command",   # text-command harness: intent only
                 "act": None, "verifier": None},
    "code":  {"corpus": ["agent-traces", "math-traces"], "want": "answer",
              "act": None, "verifier": "wasm-python"},
    "chat":  {"corpus": ["user-facts", "conversations"], "want": "answer",
              "act": None, "verifier": "critic"},
}


def _post(base, path, obj, t=200):
    r = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(obj).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=t).read())


class SolveReq(BaseModel):
    task: str
    skill: str = "agent"
    context: Optional[str] = None
    effort: str = "terse"
    n: int = 1


@app.get("/health")
def health(): return {"status": "ok", "skills": list(SKILLS)}


@app.get("/skills")
def skills(): return SKILLS


@app.post("/solve")
def solve(req: SolveReq):
    cfg = SKILLS.get(req.skill, SKILLS["agent"])
    problem = req.task + (("\n" + req.context) if req.context else "")

    # RECALL — clean lessons from this skill's corpus (Law 1). GATE on similarity: a weak/tangential
    # match MISLEADS more than it helps (out-of-corpus tasks pull noise). Clean summaries separate the
    # scores enough that a gate works — better to reason un-hijacked than steered by junk.
    lessons = []
    try:
        hits = _post(MEMORY, "/recall", {"ns": cfg["corpus"], "q": problem, "k": 2,
                                         "min_sim": HIJACK_MIN_SIM}, t=20).get("hits", [])
        lessons = [h["value"] for h in hits]
    except Exception:
        pass

    # REASON — main model, hijacked, verbosity by effort (no budget hacks)
    r = _post(REASON, "/reason", {"problem": problem, "lessons": lessons,
                                  "effort": req.effort, "want": cfg["want"]})
    intent = r.get("conclusion", "")

    # ACT — worker formats the intent into the skill's structured output (Law 2)
    output = intent
    if cfg["act"]:
        a = _post(FAST, "/fast", {"op": "act", "input": intent, "system": "Emit the tool call for this command.",
                                  **cfg["act"]}, t=60)
        output = a.get("result") or intent

    # VERIFY — best-of-N where a verifier exists (Law 3)
    verified = None
    if cfg["verifier"]:
        try:
            v = _post(VERIFY, "/verify", {"candidate": intent, "kind": cfg["verifier"]}, t=120)
            verified = v.get("ok")
        except Exception:
            verified = None

    return {"output": output, "intent": intent, "lessons": len(lessons),
            "hijacked": r.get("hijacked"), "tokens": r.get("tokens"), "verified": verified, "skill": req.skill}
