# ☀️ Sunshine

A cohesive, **model-agnostic** substrate for running small local LLMs *well* — code agents, home chat,
image/video generation & editing, and real-time speech — on commodity / idle GPUs.

**One rule:** a small-but-capable **main** model + a tiny fast **worker** (allowed to be a little dumb),
wired so either swaps out without touching anything else.
Default: **Qwen3.5-4B** (main) + **Qwen3.5-0.8B** (worker), backend **1cat-vLLM** (pluggable).

> 📐 **Read [`ARCHITECTURE.md`](./ARCHITECTURE.md) first** — it is the source of truth (the 3 laws, the
> 7 primitives, the 5 organs + kernel, the universal loop).

## Why

Small models are fast and smart only if the expensive one **never sees raw input** and **rarely runs**.
Sunshine spends cheap abundance (semantic recall + a grammar-constrained worker swarm) to keep the main
model rare and well-fed, and **verifies instead of trusting** (grammars always; WASM/test/VLM/critic when
available; best-of-N replaces guessing).

## Layout

```
ARCHITECTURE.md      source of truth
config/models.yaml   role → model → backend registry (the model-agnostic core)
organs/              memory · fast · reason · verify · kernel   (shared services)
frontends/           agent · chat · studio · voice              (kernel + 3 knobs each)
peripherals/         image/video/speech model adapters
edge/                searxng · cloudflared · open-webui (configs only)
```

## Status

Bootstrapping. Work is tracked in **GitHub Issues**; the migration is a *consolidation* of an existing
working stack (`lm-stack`), not a rewrite. See the milestones in `ARCHITECTURE.md` §Migration.

## License

MIT (see `LICENSE`).
