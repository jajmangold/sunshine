# Sunshine — Architecture (source of truth)

A cohesive, **model-agnostic** substrate for running small-but-capable local models well — across
code agents, home chat, image/video generation & editing, and real-time speech.

> **Core rule:** one *small-but-capable main model* + one *tiny fast worker* (allowed to be a little
> dumb). Everything is built so either can be swapped without touching the rest.
> Default: **Qwen3.5-4B (main)** + **Qwen3.5-0.8B (worker)**, served on **1cat-vLLM** (backend is pluggable).

---

## The thesis (one line)

**Spend abundance to make scarcity rare and well-fed.** Semantic recall (MiniLM) and the tiny-worker
swarm (grammar-constrained, ~2000 tok/s batched) are nearly free on idle GPU. Deep reasoning (the main
model) is the scarce, slow thing. So spend the cheap stuff lavishly to ensure the main model **rarely
runs** and **never sees raw input**.

## The 3 Laws (the constitution)

Every component obeys these. A change that violates a law is wrong *by construction*.

1. **Clean context** — *nothing raw reaches a reasoner.* Web pages, traces, trajectories, images, long
   docs are **distilled** (by the worker) into clean, generic, dense form *before* they are recalled or
   injected. The corpus is self-cleaning (distill-on-write).
2. **Right model for the layer** — the **worker** routes / distills / formats / judges (never invents or
   reasons); the **main model** reasons (never hand-formats). Structured output is grammar-constrained,
   not hoped for.
3. **Verify, don't trust** — every output is checked by a cheap verifier: **grammar always**;
   WASM / unit-test / critic / VLM-judge when available. **Best-of-N search replaces guessing.**

## The 7 primitives (2 tiers)

| Tier | Primitive | Engine | Role |
|---|---|---|---|
| **Fast** (lavish, swarmable) | `RECALL(ns, q, k)` | MiniLM + RaBitQ (+ColBERT) | semantic memory |
| | `DISTILL(raw → schema)` | worker + grammar | clean-before-use |
| | `ROUTE(in → enum)` | worker + grammar | pick path/model/tool |
| | `ACT(intent → grammar)` | worker + grammar | guaranteed-valid output |
| | `JUDGE(item → verdict)` | worker swarm + vote | cheap reliable micro-decision |
| **Slow** (surgical) | `REASON(problem, lessons[])` | main model + retrieval-hijack | the expensive step, fed clean |
| | `VERIFY(candidate)` | WASM / test / critic / VLM | the reward signal |

## The 5 organs + kernel

Shared services. Each product composes them; nothing is bespoke per product.

- **`memory`** — MiniLM/RaBitQ(+ColBERT). One service, **namespaced corpora** (user-facts, conversations,
  agent-traces, recipes, math-traces, prompt/asset-exemplars, web-cache, code, distilled-lessons).
  API: `write(ns, text, meta)` *(distill-on-write hook)*, `recall(ns[], q, k, rerank)`.
- **`fast`** — the tiny worker gateway. API: `{op∈{route,distill,act,judge}, grammar, input, n}`; `n>1`
  swarms + votes. Where the ~2000 tok/s batched throughput is spent.
- **`verify`** — WASM(Pyodide) + unit-test + critic + VLM-judge behind `verify(candidate, kind)` /
  `bestof(candidates, kind)`.
- **`reason`** — the main model (+ optional stronger escalation, + vision) wrapped with retrieval-hijack.
  API: `reason(problem, lessons=[], effort, model?)`.
- **`kernel`** — orchestration **library** (not a monolith) implementing the universal loop + the 3 laws
  + best-of-N + latency budget + fast→slow escalation. Imported by each front-end.

### The universal loop (every product, same shape)

```
INGEST(modality → text)            # STT, VLM-caption, file-read
  → ROUTE                          # what is this, which skill
  → RECALL(memory + corpus + web-DISTILL)
  → [ fast path: ACT ]   or   [ slow path: REASON(hijacked) → ACT ]
  → VERIFY / best-of-N             # prune where a verifier exists
  → EMIT(text → modality)          # TTS, image params, tool-call
```

**Every product = kernel + 3 knobs:** swap the **corpus** (what RECALL hits), the **grammar** (what ACT
emits), the **verifier** (how candidates prune).

| Front-end | corpus | grammar | verifier |
|---|---|---|---|
| **agent** (code/terminal) | traces + recipes | tool-call | WASM + exec |
| **chat** (OWUI) | user-facts + convo + web | answer / tags / suggest | critic |
| **studio** (image/3D/video) | prompt + asset exemplars | gen-params | **VLM-judge** |
| **voice** | chat corpus | answer | critic, *latency-budgeted* |

The **model zoo** (image/video/speech generators) are **peripherals** behind a uniform `job()` adapter
under studio/voice. SearXNG / cloudflared / OWUI are the **edge**.

## Model-agnostic backend

- A **model registry** (`config/models.yaml`) maps roles → models → backend.
- Roles: `main` (capable reasoner), `worker` (tiny fast structured), `vision`, optional `strong` (escalation).
- Backends pluggable: **1cat-vLLM** (now), vanilla vLLM, llama.cpp, OpenAI-compatible remote.
- Front-ends/organs reference **roles**, never a model name. Swapping Qwen3.5-4B → anything is one config line.

## Honest scope

This is an architecture for **small models on idle GPU**. The reasoning *ceiling* is the main model; the
substrate makes it punch up, stay cheap, and stay fast — it does **not** make it frontier. The elegance
is the **discipline (3 laws) enforced by grammars + verifiers**, not a framework.

## Migration (consolidation, not rewrite — see GitHub issues)

1. Extract **`memory`** (fold the 4 indexes + OWUI memory into one namespaced, distill-on-write service).
2. Extract **`fast`** + a reusable grammar library (kills per-site worker glue + parse/repair hand-fixes; adds swarm).
3. Promote `reason-engine` → **`kernel`** (it's already ~80%; formalize the loop + laws + escalation).
4. Refactor the 4 front-ends to kernel + 3 knobs.
5. Cross-cut: distill-on-write everywhere; verify-bus so best-of-N is universal.
6. Model swap: **Qwen3.5-4B + 0.8B** become the defaults (Nanbeige/LFM2.5i demoted to optional registry entries).
