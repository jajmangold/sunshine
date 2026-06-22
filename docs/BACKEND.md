# Sunshine as a coding backend (source of truth)

The real target: **Sunshine is a drop-in OpenAI/Anthropic backend** for real harnesses (opencode, pi.dev,
Codex, Claude Code). Terminal-Bench/Terminus was a benchmark adapter, not the goal. This doc captures the
architecture decided in the 2026-06-22 design sessions. The repo is the source of truth, not chat.

## Law 0 for the backend: be a faithful model, augment invisibly
A real Anthropic/OpenAI backend is **stateless per request but receives the entire conversation every
turn** (system + all turns + tool/skill defs). Context-maintenance, planning, and adaptation are
**emergent from the model processing the full history each turn** — there is no server-side state, and the
harness hosts the MCP servers/skills/tools. Therefore:

- **DO NOT reduce-to-task.** The task-solver shim (reduce convo → "task" string → terse reason → one
  command) was a Terminus-only crutch; it throws away the system prompt, history nuance, and tool defs. It
  would fail as an opencode backend.
- **Face the harness as a faithful model.** Full `messages` + `tools` in → response with native
  `tool_calls` (OpenAI) / `tool_use` (Anthropic) out. The harness's system prompt, tools, and recent turns
  are passed **verbatim**.
- **The Sunshine machinery is demoted to INVISIBLE AUGMENTATION**, never context replacement: gated recall
  as an *appended* system note; grammar for tool-call *validity* against the harness's own schemas;
  best-of-N + verify in the pre-emit window for code; the context engine (below) compresses only the long
  tail. The harness can't tell.

### Settled implementation decisions
- **Native tool-calling parser: NOT needed.** We do tool-calling our way — the model decides which tool
  over full context; the fast organ's grammar formats args against that tool's JSON schema; our shim
  assembles the protocol-correct `tool_calls`/`tool_use` JSON. Guaranteed-valid by construction, beats
  native parsing. (Precedent: OWUI assistant + nanbeige proxy did prompt+grammar+middleware tool-calling.)
- **Streaming: not required.** stream:false → plain JSON. stream:true forced → **buffered SSE** (compute
  everything incl. best-of-N+verify, emit as one final chunk + heartbeats). Dropping real token-streaming
  *dissolves* the best-of-N-vs-streaming tension.
- **Both surfaces in parallel**: shared kernel-backed core, OpenAI `/v1/chat/completions` AND Anthropic
  `/v1/messages`.
- **The real gate is the context window** — can the model *read* a big opencode context. Handled by the
  context engine (structured working memory), not raw 128K.

## The context engine — structured working memory (issue: context P1–P5)
A small model at 128K is nominal, not effective ("lost in the middle" hits small models hardest). Feeding
it a 6–8K **high-signal assembled working-set beats 128K raw** — a quality multiplier, not just a fit hack.
Prior art convergence: Graphiti/Zep (temporal KG), Aider repo-map (AST+PageRank), MemGPT/Letta (virtual
context paging), EDC/AdaKGC (emergent schema). We build a **light** version from our own pieces.

**Stack:** **trailmark** (Apache-2.0, tree-sitter+rustworkx, 36 langs) = the deterministic, AST-exact CODE
half; **CozoDB** (embedded Datalog, relational+graph+vector+**time-travel**) = persistence + bi-temporal
history + MiniLM/HNSW vectors + the conversation KG + SKOS. Key efficiency: **the code KG needs ZERO LLM
extraction** (trailmark diffs are deterministic); spend the worker only on the fuzzy conversation KG.

Per-turn loop (internal, harness never sees it):
```
harness resends full convo →
  DIFF (hash turns + trailmark diff of working tree) — ingest only the delta →
  INGEST: worker open-IE → convo KG (Cozo); trailmark → code graph/diff (Cozo, new validity interval) →
  ASSEMBLE the model's REAL context: system+tools+recentN VERBATIM
        + repo-map (PageRank, budgeted, boosted: id 10x / edited file 50x / complexity / untrusted-reach)
        + structural delta ("since last edit: …") + hybrid-retrieved facts + findings →
  model reasons over ~6–8K high-signal tokens → text or harness tool_call (output-shaped, below)
```
Trailmark maximized — every feature has a job: analyze→repo-map; diff→delta + temporal episodes + verify;
entrypoints/attack_surface→security context + verify escalation; augment(SARIF)→findings in context + lint
verify; QueryEngine→model nav tools + boosts; annotations→cross-turn world-state; subgraphs→focused sets.

**Phases:** P1 repo-map (DONE — `organs/context/repomap.py`, gate passed 251K LOC/6.8s) · P2 diff per turn
+ verify `trailmark-diff` · P3 CozoDB persist+temporal+convo-KG+SKOS · P4 query tools (trailmark/Cozo) +
annotations · P5 entrypoints/attack_surface + augment.

## The output-shaper — structured out (issue: output-shaper)
The output-side dual of the context engine: **define the output shape first, generate through it, cache &
RAG the shapes.** Small models fail at *format*, not content — guarantee the shape and the model only fills
content (the grammar-tool-call win, generalized to every output type). Precedent: lm-stack LFM2 fenced-JSON
router + reason-engine GBNF.
```
ask → ROUTE(output type: structured-edit/file/tool-resp/plan/json) →
      RAG(templates namespace) — retrieve best match OR worker AUTHORS a new grammar/jinja →
      GENERATE-THROUGH (grammar-constrained decode | jinja slot-fill | composed) →
      CACHE (ask→template, define-as-you-go)
```
- grammar (JSON/enums/edits) + jinja (documents) — compose; skeleton jinja, slots grammar.
- **Diffs: never a raw-diff grammar** — use a structured-EDIT shape (`{file, anchor, old, new}` / search-
  replace), grammar-constrain that, then APPLY → diff. This doubles as the **verify contract**: apply →
  `trailmark-diff` confirms structural intent → run test.
- `templates` namespace lives in the memory organ next to agent-traces/recipes; retrieved by output-type.
- Guardrail: shape the STRUCTURED outputs; leave prose/reasoning free. ROUTE confidence gates whether to
  constrain or let it run free; a mis-route is worse than no template.

## The symmetry
trailmark/Cozo **structured context IN** ↔ output-shaper **structured templates OUT** — both RAG'd, both
define-as-you-go, both making a small model reliable by taking structure off its plate.

## Reuse the reason-engine jewels (from the lm-stack review)
The kernel under-absorbed reason-engine's best code: `code_solve` (best-of-N + WASM repair) and the critic
loop. Re-express `code_solve` as a kernel **code skill** (reason N → verify.bestof → emit verified) reusing
the verify organ; flesh out `verify.critic`. Don't port the monolith.
