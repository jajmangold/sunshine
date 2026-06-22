# Ablation ladder — the proof (eval/run.py over the task suite)

Each rung must lift the curve or it's cut. Baseline = bare faithful backend (grammar tool-calls only,
no augmentation). Prefix caching enabled on sun-main (GDN-compatible ✓) — required for practical loops.

| rung | task | solved | tests | steps | sec | notes |
|---|---|---|---|---|---|---|
| 0 baseline | openssl-selfsigned-cert | ✗ | 2/6 | 14(cap) | 379 | valid tool_calls (malformed=0) but omitted `-subj` → no cert, then LOOPED `cat` with no recovery |

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
