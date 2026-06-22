# Ablation ladder — the proof (eval/run.py over the task suite)

Each rung must lift the curve or it's cut. Baseline = bare faithful backend (grammar tool-calls only,
no augmentation). Prefix caching enabled on sun-main (GDN-compatible ✓) — required for practical loops.

| rung | task | solved | tests | steps | sec | notes |
|---|---|---|---|---|---|---|
| 0 baseline (two-phase) | openssl | ✗ | 2/6 | 14 | 379 | grammar-valid (malformed=0) but omits `-subj`, then LOOPS `cat` |
| 0 single-call | openssl | ✗ | 2/6 | 14 | 361 | one-inference/step; SAME score → no quality regression, keep it |
| **1 +loop-detect** | openssl | ✗ | **5/6** | 9 | **24** | **PROVEN RUNG: 2/6→5/6 AND 361s→24s** (escapes the loop, regenerates cert, builds pem+verification). only the python-script file remains |
| **2 +repo-map** | shipping-bug (code-nav) | — | **0/3→2/3** | 12→9 | — | **PROVEN RUNG (cumulative, loop-detect on both): ~106-tok map → solve-rate 0/3→2/3, median steps 12→9.** Symptom 4 hops from cause; map gives the call-structure the 4B needs to trace pricing→discount→rules. Right tool, right task (≈no lift expected on from-scratch tasks like openssl) |
| **3 +recall** | license-gate (knowledge) | — | **0/3→3/3** | 2 | — | **PROVEN RUNG: gated recall (cos 0.769) injects a lesson with an un-derivable key. Task is sha256-preimage-resistant → bare model 0/3 (hard floor), +recall 3/3 with FEWER tokens (61 vs 151). The memory→retrieve→inject→use loop, end-to-end. This is the self-improvement moat (accumulated lessons unlock capability).** |

## Rungs to add (each measured here)
1. +loop-detection / verify-on-empty — the bare backend loops; the cheapest rung.
2. +repo-map (context-engine augment) — structural code context in the system note.
3. +recall (gated lessons) — relevant past approaches.
4. +shape (output-shaper structured-edit for write/edit) — valid edits + apply-verify.
5. +verify/best-of-N — only verified actions emitted.
6. +adaptive compute — difficulty-gated budget.

## Finding
The bare faithful backend is RELIABLE (format) but WEAK (behavior: malformed commands, looping). The
augmentation rungs are precisely what turn reliable-but-weak into excellent — and the ladder will quantify
each one's lift. Baseline took 379s/task → need the latency work (single-call tool emission) before the
full suite × all-rungs is fast enough; prefix caching was step one.
