# context engine (the working-memory substrate)

Structured, queryable working memory so a small model gets a high-signal view instead of a flat token blob.
Design: trailmark (AST code-intelligence, 36 langs, Apache-2.0) = the deterministic code half; CozoDB
(temporal-graph-vector Datalog) = persistence + time-travel + semantic vectors + the conversation KG.

## Phases
- **P1 — repo-map (DONE):** trailmark graph -> rustworkx PageRank -> conversation boosts (mentioned id 10x,
  edited file 50x) + complexity -> token-budgeted map. `repomap.py`. GATE PASSED: 251K-LOC repo (11k nodes,
  68k edges) parses in 6.8s once at session start; normal repos <0.15s; per-turn = diff changed files only.
- P2 — trailmark `diff_against` per turn -> structural delta in context + verify `trailmark-diff` kind.
- P3 — CozoDB: persist graph + MiniLM embeddings (HNSW) + bi-temporal time-travel + conversation KG
  (worker open-IE) + SKOS. One Datalog query fuses semantic + graph-reachability + relational + temporal.
- P4 — trailmark QueryEngine + Cozo queries as the model's on-demand nav tools; annotations = cross-turn state.
- P5 — entrypoints/attack_surface + augment(SARIF) -> security-aware context + verify escalation.

Runtime note: trailmark is a `uv tool` (Apache-2.0); the context organ must run in an env with
`trailmark` + `rustworkx` importable (vendor into the image, or run on host uv-tool python).
