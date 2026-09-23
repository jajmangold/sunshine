"""Sunshine · organ: fast — the tiny-worker gateway.

Two scoring paths for structured decisions:

1. ARGMAX (default for route/judge): single forward pass, logprobs over option tokens,
   argmax picks the winner. No text generation, no JSON to parse. ~3-5x faster than
   grammar-constrained decoding. Returns calibrated probabilities.

2. GRAMMAR (legacy, for act/distill): grammar-constrained JSON generation via the worker
   model. Used when the output space is unbounded or needs free-form text.

POST /fast {op, system?, input, options?, grammar?, n=1, vote, method?}
  -> {result, raw, confidence, probabilities?, n, votes?}
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

# ---- grammar library (kept for act/distill fallback) ----
_TAIL = ('str ::= "\\"" schar* "\\""\n'
         'schar ::= [^"\\\\\\n\\r\\t] | "\\\\" ["\\\\/bfnrt]\n'
         'ws ::= [ \\t\\n]?')


def g_enum(options):
    alt = " | ".join('"\\"' + o.replace('"', '') + '\\""' for o in options)
    return 'root ::= "{" ws "\\"choice\\":" ws (' + alt + ') ws "}"\nws ::= [ \\t\\n]?'


def g_bool():
    return 'root ::= "{" ws "\\"verdict\\":" ws ("true" | "false") ws "}"\nws ::= [ \\t\\n]?'


def g_toolcall(names):
    alt = " | ".join('"\\"' + n + '\\""' for n in names)
    return ('root ::= "{" ws "\\"tool\\":" ws (' + alt + ') ws "," ws "\\"command\\":" ws str ws "}"\n' + _TAIL)


GRAMMARS = {"bool": g_bool}


# ---- argmax scoring ----

def _call_api(body, timeout=60):
    """Raw POST to the worker completions endpoint."""
    r = urllib.request.Request(WORKER_URL, data=json.dumps(body).encode(),
                              headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


def _score_options(system, user, options, temperature=0.0):
    """Single forward pass, logprobs over option tokens, argmax.

    Returns (winner, confidence, {option: probability}).
    """
    # Build a prompt that ends with one of the option tokens
    option_list = ", ".join(f'"{o}"' for o in options)
    scoring_prompt = (
        f"{user}\n\n"
        f"Reply with exactly one of: {option_list}"
    )

    body = {
        "model": WORKER_MODEL,
        "temperature": temperature,
        "max_tokens": 1,
        "logprobs": True,
        "top_logprobs": len(options) + 2,
        "messages": (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": scoring_prompt}],
    }

    resp = _call_api(body)
    choice = resp["choices"][0]

    # Extract logprobs for the first generated token
    logprobs_data = choice.get("logprobs")
    if not logprobs_data or not logprobs_data.get("top_logprobs"):
        # Fallback: no logprobs available, return first option
        return options[0], 1.0, {o: (1.0 if i == 0 else 0.0) for i, o in enumerate(options)}

    top = logprobs_data["top_logprobs"][0]  # first (and only) token

    # Map option tokens to their logprobs
    scores = {}
    for opt in options:
        if opt in top:
            scores[opt] = top[opt]
        elif f'"{opt}"' in top:
            scores[opt] = top[f'"{opt}"']
        else:
            # Option token not in top logprobs — assign very low score
            scores[opt] = -999.0

    # Softmax over scores to get probabilities
    import math
    max_score = max(scores.values())
    exp_scores = {k: math.exp(v - max_score) for k, v in scores.items()}
    total = sum(exp_scores.values())
    probs = {k: v / total for k, v in exp_scores.items()}

    winner = max(probs, key=probs.get)
    confidence = probs[winner]

    return winner, confidence, probs


def _score_bool(system, user, temperature=0.0):
    """Score true/false with argmax. Returns (verdict, confidence, {bool: prob})."""
    scoring_prompt = f"{user}\n\nReply with exactly one word: true or false"

    body = {
        "model": WORKER_MODEL,
        "temperature": temperature,
        "max_tokens": 1,
        "logprobs": True,
        "top_logprobs": 4,
        "messages": (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": scoring_prompt}],
    }

    resp = _call_api(body)
    choice = resp["choices"][0]
    logprobs_data = choice.get("logprobs")

    if not logprobs_data or not logprobs_data.get("top_logprobs"):
        return True, 0.5, {True: 0.5, False: 0.5}

    top = logprobs_data["top_logprobs"][0]

    true_score = top.get("true", top.get("True", -999.0))
    false_score = top.get("false", top.get("False", -999.0))

    import math
    max_s = max(true_score, false_score)
    exp_t = math.exp(true_score - max_s)
    exp_f = math.exp(false_score - max_s)
    total = exp_t + exp_f
    probs = {True: exp_t / total, False: exp_f / total}

    winner = max(probs, key=probs.get)
    return winner, probs[winner], probs


# ---- grammar fallback (for act with unbounded output, distill) ----

def _call_grammar(system, user, grammar, max_tokens, temp):
    body = {"model": WORKER_MODEL, "temperature": temp, "max_tokens": max_tokens,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]}
    if grammar:
        body["structured_outputs"] = {"grammar": grammar}
    r = urllib.request.Request(WORKER_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())["choices"][0]["message"]["content"]


# ---- API ----

class FastReq(BaseModel):
    op: str                                          # route | distill | act | judge
    input: str
    system: Optional[str] = None
    grammar: Optional[str] = None
    grammar_name: Optional[str] = None
    options: Optional[List[str]] = None              # route/act(tool) enum
    n: int = 1
    vote: str = "majority"                           # majority | best
    method: Optional[str] = None                     # argmax | grammar (auto-select if None)
    max_tokens: int = 256
    temperature: float = 0.2


def _should_use_argmax(req: FastReq) -> bool:
    """Decide whether to use argmax scoring or grammar generation."""
    if req.method == "argmax":
        return True
    if req.method == "grammar":
        return False
    # Auto-select: argmax for route/judge with options, grammar for act/distill
    if req.op in ("route", "judge") and req.options:
        return True
    if req.op == "judge":
        return True
    return False


@app.get("/health")
def health(): return {"status": "ok", "worker": WORKER_MODEL}


@app.post("/fast")
def fast(req: FastReq):
    if _should_use_argmax(req):
        return _fast_argmax(req)
    return _fast_grammar(req)


def _fast_argmax(req: FastReq):
    """Argmax scoring path — no text generation, just logprobs."""
    system = req.system or (
        "Choose the single best option." if req.op == "route"
        else "Answer with a strict verdict."
    )

    def one(_):
        try:
            if req.op == "judge":
                verdict, conf, probs = _score_bool(system, req.input, req.temperature)
                return {"result": verdict, "confidence": conf, "probabilities": probs}
            elif req.op == "route" and req.options:
                winner, conf, probs = _score_options(system, req.input, req.options, req.temperature)
                return {"result": winner, "confidence": conf, "probabilities": probs}
        except Exception:
            return None

    if req.n <= 1:
        r = one(0)
        if r is None:
            return {"result": None, "n": 1}
        return {"result": r["result"], "confidence": r["confidence"],
                "probabilities": r["probabilities"], "n": 1, "method": "argmax"}

    # Swarm: run n times and majority-vote
    with ThreadPoolExecutor(min(req.n, 32)) as ex:
        results = [r for r in ex.map(one, range(req.n)) if r is not None]
    if not results:
        return {"result": None, "n": req.n, "votes": {}}

    if req.vote == "majority":
        tally = Counter(r["result"] for r in results)
        winner_val, count = tally.most_common(1)[0]
        # Average confidence across votes for the winner
        winner_confs = [r["confidence"] for r in results if r["result"] == winner_val]
        avg_conf = sum(winner_confs) / len(winner_confs) if winner_confs else 0.0
        # Merge probabilities by averaging
        merged_probs = {}
        for r in results:
            for k, v in r.get("probabilities", {}).items():
                merged_probs[k] = merged_probs.get(k, 0) + v / len(results)
        return {"result": winner_val, "confidence": avg_conf, "probabilities": merged_probs,
                "n": req.n, "votes": dict(tally), "method": "argmax"}

    return {"result": results[0]["result"], "confidence": results[0]["confidence"],
            "n": req.n, "method": "argmax"}


def _fast_grammar(req: FastReq):
    """Grammar-constrained generation path (legacy, for act/distill)."""
    if req.op == "route":
        grammar = g_enum(req.options or ["yes", "no"])
        system = req.system or "Choose the single best option."
        parse = lambda s: json.loads(s).get("choice")
    elif req.op == "judge":
        grammar = g_bool()
        system = req.system or "Answer with a strict verdict."
        parse = lambda s: json.loads(s).get("verdict")
    elif req.op == "act":
        if req.options:
            grammar = g_toolcall(req.options)
            system = req.system or "Emit the tool call."
            parse = lambda s: json.loads(s)
        else:
            grammar = req.grammar or (GRAMMARS[req.grammar_name]() if req.grammar_name in GRAMMARS else None)
            system = req.system
            parse = lambda s: json.loads(s) if grammar else s
    else:  # distill
        grammar = req.grammar
        system = req.system or "Distill into ONE clean generic lesson, omit specifics."
        parse = lambda s: s.strip()

    def one(_):
        try:
            return parse(_call_grammar(system, req.input, grammar, req.max_tokens, req.temperature))
        except Exception:
            return None

    if req.n <= 1:
        return {"result": one(0), "n": 1, "method": "grammar"}

    with ThreadPoolExecutor(min(req.n, 32)) as ex:
        results = [r for r in ex.map(one, range(req.n)) if r is not None]
    if not results:
        return {"result": None, "n": req.n, "votes": {}}
    if req.vote == "majority":
        try:
            tally = Counter(json.dumps(r, sort_keys=True) if not isinstance(r, (str, bool, int)) else r for r in results)
            winner, votes = tally.most_common(1)[0]
            win = next(r for r in results if (json.dumps(r, sort_keys=True) if not isinstance(r, (str, bool, int)) else r) == winner)
            return {"result": win, "n": req.n, "votes": dict(tally), "method": "grammar"}
        except Exception:
            pass
    return {"result": results[0], "n": req.n, "all": results, "method": "grammar"}
