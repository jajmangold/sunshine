# vLLM patch: LoRA serving on Qwen3.5 GDN-hybrid (VL checkpoint)

**Problem.** `--enable-lora` crashes the engine at init on Qwen3.5-4B with
`IndexError: lora_a[i]` in `vllm/lora/layers/column_parallel_linear.py::set_lora`.

**Diagnosis (2026-06-24).** LoRA *is* supported on the GDN arch — the text-only class
`Qwen3_5ForCausalLM` declares `SupportsLoRA` with a correct mapping. But Qwen3.5-4B ships **only** as a
multimodal (VL) checkpoint → vLLM loads `Qwen3_5ForConditionalGeneration`, whose LoRA setup tries to wrap the
**GDN linear-attention `in_proj` layers**, and the dummy-LoRA construction mis-slices them → IndexError.
(fp16 and int4 fail identically → it's the arch path, not quant; the VL `packed_modules_mapping` is not the
cause — dropping the vision `qkv` group doesn't fix it.)

**Fix.** Restrict LoRA to the standard projections by removing the GDN `in_proj` entries from the **VL class's**
`packed_modules_mapping` (file `qwen3_5.py`). LoRA then targets `qkv_proj` (full-attention layers) +
`gate_up_proj` (every layer's MLP) — ample adaptation capacity; only the GDN mixing projections go un-adapted.
Base serving is unaffected (our AutoRound int4 checkpoint doesn't need the fused in_proj mapping to load).

**VERIFIED end-to-end (sm70 V100):** engine boots with `--enable-lora`, a LoRA adapter loads via
`--lora-modules`, and a request against it applies + returns a valid response. LoRA kernels run on Volta.

**Apply:** mount `qwen3_5.py` over `…/vllm/model_executor/models/qwen3_5.py` in the gdnmin image (read-only),
or bake into the image. This re-opens dynamic LoRA → Text-to-LoRA / Doc-to-LoRA / per-class LoRA / merge-distill.
