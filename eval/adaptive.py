"""Adaptive compute — start cheap, escalate only when the verifier fails (the last lever).

Easy turns stay fast (bare, single attempt); hard turns climb an escalation ladder
(+ augmentation → + best-of-N). The verifier is the difficulty signal — REACT, don't predict. Goal: match
always-full-budget reliability at far lower cost on the easy majority.

  python adaptive.py <adaptive|full> <task...>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run as R

STEPS = 14
# escalation ladder: each rung adds compute, entered only on the prior rung's verifier FAILURE
LADDER = [
    {},                                      # tier 1: BARE — cheapest (no recall, no repo-map)
    {"RepoMap": "on", "Recall": "on"},       # tier 2: + augmentation (repo-map + recall)
    {"RepoMap": "on", "Recall": "on"},       # tier 3: + another verified-best-of-N attempt
]
FULL = {"RepoMap": "on", "Recall": "on"}     # the non-adaptive baseline: full budget every attempt


def adaptive(name):
    tok = sec = 0
    for i, tier in enumerate(LADDER, 1):
        r = R.run(name, steps=STEPS, ablation=dict(tier), label=f"adapt-t{i}")
        tok += r["tokens"]; sec += r["sec"]
        if r["solved"]:
            return True, i, tok, sec
    return False, len(LADDER), tok, sec


def full(name, n=3):
    tok = sec = 0
    for k in range(1, n + 1):
        r = R.run(name, steps=STEPS, ablation=dict(FULL), label=f"full-{k}")
        tok += r["tokens"]; sec += r["sec"]
        if r["solved"]:
            return True, k, tok, sec
    return False, n, tok, sec


if __name__ == "__main__":
    mode = sys.argv[1]
    for t in sys.argv[2:]:
        s, a, tok, sec = (adaptive if mode == "adaptive" else full)(t)
        print(f"RESULT {mode:8} {t:16} {'PASS' if s else 'fail'} | attempts {a} | tokens {tok} | {sec}s", flush=True)
