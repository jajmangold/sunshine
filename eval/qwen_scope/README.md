# Qwen-Scope steering — training-free, weight-free, on-the-fly adaptation

The "no-training adaptive hypernetwork": Qwen's open-source SAE suite (arxiv 2605.11887) decomposes the
residual stream into ~32K interpretable features per layer. Steering = add a feature's decoder direction
(`W_dec[:,j]`) to the residual at inference -> behavior shifts toward that concept. No weights changed, no
gradient, no LoRA. The activation-steering analog of our env-grounding prompt — but mechanistic.

## PROVEN (2026-06-24, Qwen3.5-2B base + SAE-Res-Qwen3.5-2B-Base-W32K-L0_50, layer 14, V100)
Steered a neutral generation ("My favorite thing to think about is...") from *dark energy* to *the ocean*
("the largest ecosystem... 300 species of fish") with one feature direction. coeff sweep:
0.0 neutral -> 0.2 clean ocean theme -> 0.35 over-steers. See steer_demo.py.

## Two findings that make it actually work
1. **Contrastive feature selection is required.** Top-activation features are GENERIC (BOS/syntax, fire on any
   text — same ids across unrelated probes). The concept feature = argmax(mean_act(concept) - mean_act(neutral)).
2. **Scale the perturbation to the residual norm** (`coeff * resnorm * unit_direction`). Raw large coeffs (6-12)
   degenerate to token repetition; ~0.2*resnorm is the coherent sweet spot.

## SCOPE (what's available)
SAEs exist for Qwen3.5-2B / 9B / 27B / 35B-A3B and Qwen3-1.7B/8B/30B (BASE models) — NOT our 4B main.
We RUN a Qwen3.5-9B (lm-stack qwen9b) -> the 9B SAE is directly applicable. Needs the model in transformers
(residual hooks), not vLLM/llama.cpp. transformers must be >=qwen3_5-aware (4.57.6 too old; -U fixes it).

## Path to OUR use (mechanistic env-grounding)
Contrastively find the behavioral features (concept="check permissions / don't fight tmux / verify assumptions"
vs neutral) on the 9B SAE, steer them during agentic generation = the ENV_NOTE prompt done in weight-space.
HONEST BOUNDARY: steering controls behavior/concepts (the edge class, like env-grounding 1->3), bounded by the
model's capacity — it will NOT inject capability (won't teach openssl). Same boundary; cleaner, training-free lever.
