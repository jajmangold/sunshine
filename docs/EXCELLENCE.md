# What "excellent" means, and how we'll know (source of truth)

The goal isn't "works" — it's **demonstrably the best system you can build around a given model.** This doc
defines the fully-realized vision, the best-known pattern at every level, and — the part most systems
hand-wave — **how we prove it's better.**

## The deepest pattern (visible at every level): generator + cheaper verifier
Verifying is cheaper than generating. A small model becomes reliable when every output is checked by a
cheaper oracle. This appears at every layer and is the spine of the whole design:
- L0 decode → **grammar** (xgrammar) guarantees shape.
- L1 call → **self-consistency vote** (swarm) / **best-of-N + verifier**.
- L2 turn → **WASM test / trailmark-diff / critic** guard the action before emit.
- L4 learning → only **verified** outcomes become memory (the verifier guards the learning loop).
- dev → the **ablation eval** is the verifier of the whole system.
Where we lack a verifier (free-form prose) we are weakest → push every output toward a checkable form
(structured edits, typed args, executable artifacts).

## The fully-realized TURN (L2) — every rung
INGEST faithful full context → **DIFF** (process only the delta: text turns + trailmark structural diff) →
**ESTIMATE difficulty** (cheap worker/heuristic → compute budget) → **ASSEMBLE** high-signal working-set
(system+tools+recentN verbatim + repo-map + structural delta + gated recall + findings; budget scales w/
difficulty) → **REASON** (effort scales; hijacked by recalled lessons over clean context) → **SHAPE**
(output through grammar/template, valid by construction) → **VERIFY before emit** (scales: trivial=none,
hard=best-of-N + test + trailmark-diff + critic) → **EMIT** protocol-faithful → **LEARN** (verified-only:
distill lesson, cache template, record trajectory).

## The levels and their best-known patterns
| level | best pattern | status |
|---|---|---|
| L0 decode | constrained decoding (+ speculative) | ✅ grammar |
| L1 call | generator+verifier, self-consistency, prefill-steer, right-effort | ◻ partial |
| L2 turn | verifier-guarded ReAct + **adaptive test-time compute** | ◻ pieces |
| L3 session | virtual memory (MemGPT) + structured retrieval (repo-map/GraphRAG) + temporal KG (Graphiti) | ◻ P1 |
| L4 cross-session | verified distill-on-write, growing skill/template library (Voyager), trajectory RAG | ◻ seeded |
| L5 system | model-agnostic organs + kernel loop + verify-everywhere + **determinism-first** | ✅ skeleton |

**The excellence multiplier = adaptive test-time compute**: estimate difficulty per turn, spend the
abundance (context depth, sample N, thinking effort, verification depth, recall) WHERE IT MATTERS. Easy
turns stay fast; hard turns get fed. Keep the common path single-shot or it's reliable-but-unusably-slow.

## HOW WE KNOW IT'S BETTER (falsifiable, dogfooded)
A first-class **eval/ablation harness** is the keystone, not an afterthought. The claims + their metrics:
1. **Reliable by construction** — malformed-output rate ≈ 0 (grammar) vs raw model's nonzero.
2. **Capability-per-dollar** — success-vs-$ frontier: Sunshine+model beats raw-model at every size (the
   substrate LIFT is positive everywhere → "best system around a given model").
3. **Context-efficient** — success at a FIXED token budget: assembled working-set > raw truncation.
4. **Deterministic where possible** — code-fact accuracy (trailmark) vs the model guessing.
5. **Self-improving** — success RISES with usage on a FIXED held-out eval as libraries grow (most agent
   frameworks are stateless across sessions; we accumulate — the moat).

The decisive experiment is the **ABLATION LADDER**:
`raw → +grammar → +repo-map → +recall → +shape → +verify/best-of-N → +adaptive-compute`.
Every rung must lift the curve or it's CUT. The ladder is the proof AND the dev guardrail (no regressions).
Nothing ships that doesn't move the eval.

## Honest risks (the vision isn't naive)
- Latency: keep easy path single-shot; cheap difficulty estimator; verifier catches under-spend → retry.
- Verifier coverage: prose has no executable check → push to checkable forms; critic-vote is the weak
  fallback; prose quality honestly rides on the model.
- The model ceiling is real → answer is model-agnostic (same substrate lifts a bigger model; prove via the
  per-size lift).
- Over-engineering → the ladder is the discipline; build the eval FIRST.

## Build order (forced)
A. **eval/ablation harness** (keystone + dogfood vehicle) — drive the BACKEND on a task suite, ablation flags, scorecard.
B. wire turn-loop rungs into the backend one at a time, each proven on the ladder: repo-map → recall → shape → verify/best-of-N.
C. verified **distill-on-write** (self-improvement loop) + the self-improvement curve.
D. **adaptive compute** (difficulty estimator → budget).
E. rest: Cozo temporal + query tools, Anthropic harness test, other front-ends.

## Dogfood
trailmark on our own repo (the repo-map is OF us); the harness drives our own backend; opencode/pi on
Sunshine for small verified edits; memory/templates accumulate from our own sessions. If it can't help
build itself on a task, that's a measured boundary — logged, not hidden.
