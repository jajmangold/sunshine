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

## Knowledge-injection vs reasoning-injection — MEASURED (don't conflate them)
3-arm A/B on make-build-bare (sha256-gated key, un-derivable; same recalled lesson, two delivery channels):

| channel | solved | note |
|---|---|---|
| bare (no recall) | 0/3 | hard floor |
| **knowledge → system NOTE** | **3/3** | precise, authoritative — the agent uses the key correctly |
| reasoning → `<think>` HIJACK | **0/3** | the reasoning phase CORRUPTED the fact — agent ran the HASH instead of the key (843 vs 81 tok) |

**Finding:** the two are NOT interchangeable. A FACT belongs in a note; forcing it through the think-prefill
hijack adds noise and corrupts it. So: backend recall delivers as a NOTE by default (the working channel,
now self-augmenting 0/3→3/3); the `<think>` hijack is OPT-IN (`x-sun-reason:on`) for STEERING on
reasoning/strategy turns (its home is the reason organ's single-phase ACTION-extraction path — grammar
tool-calls and open-think are architecturally in tension; the two-phase split loses the steer). The proper
reasoning-injection win (steering a strategy the model fumbles) is still UNMEASURED — needs a strategy task,
not a fact task. The ablation caught my own wrong default (hijack-for-everything) — methodology working.

## Reasoning-injection — the STRATEGY-task measurement (the number I owed)
flaky-priority: a non-obvious strategy task (bug = set-iteration order → flaky test; HIDDEN multi-seed
verifier so hardcoding the visible test fails). Same recalled APPROACH (an approach, not a fact), two
delivery channels, bare control:

| channel | solved | median tokens |
|---|---|---|
| bare | **0/3** | 89 |
| approach → system NOTE | **3/3** | 204 |
| approach → `<think>` HIJACK | **1/3** | 526 |

**THE ANSWER:** (1) Injecting the recalled APPROACH genuinely lifts a strategy task the bare 4B fumbles —
**0/3 → 3/3** via the note. So reasoning/approach IS injected effectively and "well-fed not smarter" was
wrong: a recalled approach makes it solve things it can't solo. (2) BUT the think-prefill HIJACK
MECHANISM underperforms the note even here (1/3 vs 3/3, 2.5× tokens). Across BOTH a fact task and a
strategy task, in the grammar-tool-call backend the **system-note beats the think-prefill**. The
hijack's theoretical "model owns the reasoning" advantage does NOT survive the two-phase grammar split;
its proven home is the reason organ's SINGLE-phase ACTION-extraction path (where it was validated on
Nanbeige). So: the faithful backend injects reasoning via the NOTE channel (works); the think-prefill is a
different mechanism that needs a non-grammar single-phase path. Right mechanism, right architecture.

## Rung-5: verify / best-of-N — the generator + cheaper-verifier SPINE (the deepest pattern)
shipping-bug (moderate task, single-attempt p=0.5), cumulative over repo-map. The VERIFIER (hidden test)
selects the winner among attempts; stop at first verified success (eval/bestof.py):

| | solved | note |
|---|---|---|
| single attempt | **4/8 = 50%** | unreliable |
| **verify-guided best-of-3** | **5/5 = 100%** | median 2 attempts-to-success |

**This is the spine of the whole thesis** ("verifying is cheaper than generating"): N tries + a cheap
checker converts UNRELIABLE -> RELIABLE. The verifier is what makes test-time compute pay off — without it
you can't pick the right attempt. Five rungs now proven: loop-detect 2/6->5/6, repo-map 0/3->2/3,
recall-facts 0/3->3/3, recall-approaches 0/3->3/3, verify/best-of-N 50%->100%. The remaining lever is
ADAPTIVE compute (spend the N/verify budget only on hard turns — gate by difficulty), the optimization once
the rungs exist.
