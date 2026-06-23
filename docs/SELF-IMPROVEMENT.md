# How far can it take itself? (theory + measured evidence)

## The honest law
**Self-improvement here is AMPLIFICATION, not creation, and its reach equals the verifier's reach.**
The system makes a given model maximally effective and accumulates *verified* experience on the workload
it sees. It cannot manufacture reasoning the base model lacks, nor improve on axes it can't measure.

## Four loops, four ceilings
1. **Knowledge accumulation** (recall moat) — solve → distill verified lesson → future similar tasks
   recall it. Ceiling: experience distribution × whether lessons transfer. *Proven: license-gate 0/3→3/3.*
2. **Verified-data flywheel** — generate → VERIFY → keep only verified → accumulate → solve more. Ceiling
   = verifier coverage × the base model's *occasional*-success rate. Converts occasional→reliable. You can
   only keep what you can occasionally produce AND verify. *Proven below.*
3. **Self-construction (dogfood)** — writes its own organs/tasks/lessons. Ceiling: verified *mechanical*
   work only; architecture comes from outside.
4. **Curriculum self-generation** — generates its own tasks + finds its own weak spots. Ceiling: its own
   conceptual reach; novelty enters from outside.

## The asymptote (precise)
The **reliable-capability frontier converges up to the base model's raw-capability frontier** on the
workload it sees — cheaper and more reliable over time — then **stops**. It never exceeds raw capability.
But: reliability asymptotes ≈100% (grammar/verify are near-total verifiers); cost falls monotonically
(we measured recall cut tokens 151→61); and **the model is swappable**, so the whole ceiling rises with
the frontier for free and the accumulated library transfers. "Far" = *maximally effective use of whatever
model you give it, self-extending its reliable reach across its experience, forever cheaper* — a moving
ceiling pinned to the model frontier, not a fixed wall.

## Reasoning-injection — MEASURED (strategy task)
Injecting a recalled APPROACH (not a fact) lifts a strategy task the bare 4B fumbles: bare 0/3 → 3/3 (flaky-priority). So a small model DOES reason better when handed a relevant approach — but the DELIVERY matters: the **system-note beats the `<think>`-hijack** in the grammar backend (note 3/3 vs hijack 1/3 even on a strategy task; on a fact task 3/3 vs 0/3). The hijack's 'owns the reasoning' edge needs the reason organ's single-phase ACTION-extraction path, not the two-phase grammar bolt-on. Net: reasoning-injection is real and works (via note); the think-prefill is a separate mechanism with a narrower home.

## Reasoning-injection — the lever that moves the ceiling (CORE)
"Well-fed, not smarter" is INCOMPLETE. Besides knowledge-injection (facts → system note), the substrate
does **reasoning-injection**: recall a relevant **reasoning trace** → inject it as an **unclosed `<think>`
prefill** so the model OWNS and continues it (the Nanbeige retrieval-hijack; `frontends/backend/app.py`
`recall_reasoning` + `_reason_prefill`, default-on, gated by a strong trace hit). This lifts the model's
*in-practice* reasoning from "what it can **generate** solo" up to **"what it can FOLLOW and VERIFY"** — a
genuinely higher ceiling. With traces from a *stronger* source, the small model can follow steps it could
never have generated (distillation-at-inference). It is amplification + transfer, **bounded by
follow-ability/verify-ability** (inject reasoning it can't follow → it mangles the next step), and the
trace must originate somewhere (verified prior success / stronger model / human).

## What it CANNOT do (irreducible)
- Manufacture reasoning from NOTHING (the trace must come from somewhere) or follow reasoning beyond its
  follow-and-verify ceiling (the 4B wall is real — but it's "follow+verify," not "generate").
- Learn **un-derivable knowledge** without an external source (license-gate proves outside-input is
  irreducible — sha256 preimage-resistance makes 0/3 a hard floor).
- Improve on **unverifiable** axes (prose/taste/novel-design don't ratchet).
- Accumulate safely without a verifier — **unverified accumulation is NEGATIVE** (noise poisons recall).

## MEASURED EVIDENCE — the flywheel, end-to-end, no human seeding
Task family `make-build-*`: a build gated by `sha256(RELEASE_KEY)==<hash>` (the key is **un-derivable** from
the files). The plaintext key (`GOLD-7731`) appears ONLY in the *hinted* variant's README.

1. **LEARN** — system runs `make-build-hinted`, discovers the key in the README, builds (8 steps), and
   **auto-distills a lesson from its OWN verified success** (`--distill`, verified-only) → stored at cos 0.872, contains the key.
2. **FLYWHEEL TEST** — `make-build-bare` (no README; key un-derivable):

   | bare task | solved |
   |---|---|
   | no recall (control) | **0/3** — hard floor (can't reverse sha256) |
   | recall the self-distilled lesson | **3/3**, 4 steps each |

**The system taught itself the key from its own success and used it to solve a task that is
information-theoretically impossible without that knowledge.** That is self-propulsion — *measured*, not
argued. And its limit is equally clear: the key had to enter from outside ONCE (the README); the flywheel
amplified that single discovery into reliable capability. Amplification up to the verifier's reach,
pinned to the model frontier. That's how far.
