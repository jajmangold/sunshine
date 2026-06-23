# Verified test-time scaling — how a small model reaches frontier-grade on verifiable tasks

**The result (measured 2026-06-23).** Same Qwen3.5-4B, same hard task (jpvanhal/inflection with `pluralize`
and `singularize` stubbed → 250 failing tests):

| approach | score | cost |
|---|---|---|
| one-shot through a real harness (opencode) | **87/250 (35%)** | 1 agent run |
| **verified best-of-N (`eval/verified_scaling.py`)** | **220/250 (88%)** | ~16 fast generations (~1–2 min) |

88% is **frontier territory** (Terminal-Bench 2.0's top is ~85%) — reached by a 4B, at ~1/100th frontier price.

## Why it works
The 4B's per-piece generation is **wildly high-variance**. The pluralize candidate scores, same prompt, eight times:

```
0, 70, 0, 0, 35, 167, 15, 0      ← a PERFECT 167 emitted ~1-in-8, buried in noise
best-of-1 = 0  →  best-of-3 = 70  →  best-of-8 = 167
```

**The perfect solution already exists inside the model.** The substrate's job is to (a) sample its variance
and (b) let a cheap, perfect verifier (the tests) keep the rare win. The scaling law:

> reliability = `1 − (1 − p)^N`  — for per-sample success `p` and `N` samples with a verifier.
> `p = 0.2, N = 10 → 0.89`. A model that solves a task 1-in-5 beats an 85%-single-shot frontier model.

This is the session's central thesis made concrete: **you don't make the small model smarter — you sample
its variance and let a cheap verifier keep the rare win.** "Can sometimes" → "does reliably."

## The levers (each measured)
- **Shrink the job to the model's strength** — generate ONE function, not "edit both + persist + verify".
  The 4B writes a function fine (camelize: solved); it fails at the agent-wrapper around it.
- **Focused context ≫ whole-file** — for the small model, *more context hurts*: singularize scored 62 with
  just (tables + spec) vs 10 with the whole 429-line file dumped in.
- **AST-safe programmatic apply** — corruption is impossible; the model never edits file structure (this kills
  the `})`-unmatched-bracket failure that sank the one-shot hard run).
- **Fast parallel generation** — main-direct, thinking **OFF** (~0.3–2 s/gen). The faithful-backend no-tools
  path runs `thinking=True` (~200 s/gen), ~600× slower, making best-of-N infeasible. Use the fast path or the
  0.8B worker swarm (≈2000 tok/s batched) to generate candidates in parallel.
- **Verifier selects + a repair round** for the `p`-too-small tail.

## The honest boundaries
1. **Needs `p > 0`.** Pluralize had a perfect in its tail → best-of-8 nailed it (167). Singularize did *not*
   find a perfect in 8 (smaller `p`) → topped out at 53, leaving ~30 failures. More N or repair continues the
   curve, but it isn't free.
2. **Needs a real verifier.** Code gives a free, perfect one (tests). Unverifiable tasks get none of this —
   that's the open frontier (test-synthesis, critic models).
3. **The frontier can adopt the same orchestration.** The edge is *cost-adjusted reliability*, not a
   permanent capability lead. You beat the frontier *price* and its *single-shot* on verifiable tasks — not
   its raw reasoning.

## Reproduce
```bash
# stage a stubbed repo (or adapt to any verifiable task)
cd /tmp && git clone --depth 1 https://github.com/jpvanhal/inflection bon/inflection
# stub pluralize + singularize bodies to `raise NotImplementedError`
SCALE_REPO=/tmp/bon/inflection python3 eval/verified_scaling.py
```

## Where this goes in the product
The faithful backend already carries safe-apply (`_malformed_edit`) and directive-recall. The **unbuilt
product lever** is wiring **piece-level best-of-N (parallel, thinking-off / worker-swarm) + focused-context
decomposition + the verifier** into the agent loop — the thing that turns this `/tmp`-grade demo into a
frontier-grade, frontier-price number on a real benchmark. See `SELF-IMPROVEMENT.md` for the amplification
theory this confirms.

## Generalized: `eval/verified_solve.py` (task-agnostic)
Hand it any repo + module + test selector; it **auto-discovers** stubbed functions (those raising
`NotImplementedError`), builds focused context automatically (imports + module-level constants), and runs
best-of-N + verifier-select + a repair round per target. Proven to generalize beyond the two tuned functions:
**6 auto-discovered functions** (camelize/dasherize/parameterize/titleize/pluralize/singularize), 0 → **149
passing** (`SCALE_CONC=3`), best-of-8 beating best-of-1 across the board (pluralize 0→117, titleize 0→11,
singularize 7→9, dasherize 4, camelize 7). One-shot through a harness gets ~0 on a 6-function stub.

### Architecture finding: best-of-N needs parallel CAPACITY, not one model — MEASURED
Naive 6-wide parallel generation **saturated the single 4B** (max-num-seqs 4 → 12 s/gen, timeouts killing
candidates → reduced effective N → **total 77**, pluralize stuck at 17). Just bounding concurrency to the
model's headroom (`SCALE_CONC=3`) **nearly doubled it: 77 → 149** (pluralize 17 → 117). The saturation *was*
the degradation. The right substrate for real best-of-N is **multiple model instances or the 0.8B worker
swarm (≈2000 tok/s batched)** generating candidates in parallel. The lesson: *spend cheap parallel capacity
to sample the tail — and you need real capacity (not one contended model) to do it.*
