# Validated serving config (issue #1) — Qwen3.5 on 1cat-vLLM (gdnmin), sm70

Both Intel AutoRound int4 models load + run. Qwen3.5 is a **GDN-hybrid, natively multimodal** family —
hence the gdnmin image (GDN support) and the gotchas below.

## Gotchas (required)
- **Tokenizer:** patch `tokenizer_config.json` `tokenizer_class: TokenizersBackend → Qwen2Tokenizer`
  (gdnmin transformers lacks the new TokenizersBackend).
- **Text-only:** pass `--limit-mm-per-prompt '{"image":0,"video":0}'` — these are VL models; skip the vision tower.
- **Memory:** GDN spikes on compile. Use **16GB cards** (12GB V100 OOMs under load); conservative `--gpu-memory-utilization`.
- **KV:** `--kv-cache-dtype fp8_e5m2`. Quant: `--quantization auto-round` (INC path).

## Worker — Qwen3.5-0.8B  (role: fast)   [16GB CMP, util 0.88]
`--max-model-len 8192 --max-num-seqs 64 --kv-cache-dtype fp8_e5m2`
→ grammar (GBNF/xgrammar) ✅ · single 219 tok/s · **batched 32× = 2220 tok/s** (swarm-ready)

## Main — Qwen3.5-4B  (role: reason)   [16GB CMP, util 0.80]
`--max-model-len 8192 --max-num-seqs 12 --gpu-memory-utilization 0.80`
→ ~100–110 tok/s warm · **`enable_thinking` toggle works** (chat_template_kwargs): off=99tok/1s, on=1104tok/10s
→ the toggle is the agent-timeout fix that Nanbeige lacked.
