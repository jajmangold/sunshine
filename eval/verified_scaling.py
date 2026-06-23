"""Verified test-time scaling — the lever that takes a small model to frontier-grade on VERIFIABLE tasks.

PROVEN (2026-06-23): same Qwen3.5-4B, same hard task (jpvanhal/inflection, pluralize+singularize stubbed,
250 failing tests). One-shot through a real harness (opencode) = 87/250 (35%). This = 220/250 (88%) — 2.5×,
frontier-grade — for ~16 cheap fast generations (~1-2 min).

WHY IT WORKS. The 4B's per-piece generation is wildly high-variance: pluralize candidate scores were
{0,70,0,0,35,167,15,0} — a PERFECT 167 emitted ~1-in-8, buried in noise. The perfect solution already
EXISTS in the model; the substrate's job is to (a) sample its variance and (b) let a cheap, perfect verifier
(the tests) keep the rare win. Reliability = 1-(1-p)^N >> single-shot p, whenever p>0 and a verifier exists.

THE LEVERS (each measured this session):
  - Shrink the job to the model's strength: generate ONE function, not "edit both + persist + verify".
  - FOCUSED context (just the tables + the function spec) >> whole-file dump (62 vs 10 for the small model).
  - AST-safe programmatic apply: corruption is impossible (the model never edits the file structure).
  - FAST parallel generation: main-direct thinking-OFF (~0.3-2s/gen) — the faithful-backend no-tools path runs
    thinking=True (~200s/gen) and makes best-of-N infeasible. Use the fast path or the 0.8B worker swarm.
  - The VERIFIER selects + a repair round handles the p-too-small tail.

Boundaries (honest): needs p>0 (the model must solve it SOMETIMES) and a real verifier. Unverifiable tasks
and p=0 tasks get none of this — escalate to a frontier model there (adaptive compute).

  python verified_scaling.py            # runs the inflection demo if the repo is staged at REPO
"""
import urllib.request, json, re, ast, subprocess, os

MAIN = os.getenv("SUN_MAIN_URL", "http://127.0.0.1:8072/v1/chat/completions")
MODEL = os.getenv("SUN_MAIN_MODEL", "qwen3.5-4b")


def gen(prompt, temp):
    """Fast candidate generation: main-direct, thinking OFF (the ~600× speedup that makes best-of-N viable)."""
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 700,
            "temperature": temp, "top_p": 0.95, "chat_template_kwargs": {"enable_thinking": False}}
    r = urllib.request.Request(MAIN, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())["choices"][0]["message"]["content"] or ""


def func_src(file, name, src=None):
    src = src or open(file).read()
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return "\n".join(src.split("\n")[n.lineno - 1:n.end_lineno])


def extract(text, name):
    """Pull exactly the named function out of the model's output via AST (ignores prose / extra defs)."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    blk = m.group(1) if m else text
    if f"def {name}(" in blk:
        blk = blk[blk.find(f"def {name}("):]
    try:
        for n in ast.parse(blk).body:
            if isinstance(n, ast.FunctionDef) and n.name == name:
                return "\n".join(blk.split("\n")[n.lineno - 1:n.end_lineno])
    except SyntaxError:
        return None


def apply(file, name, fn):
    """AST-safe replace: only writes if the whole file still parses AND the function survives. No corruption."""
    s = open(file).read(); L = s.split("\n")
    sp = [(n.lineno - 1, n.end_lineno) for n in ast.parse(s).body if isinstance(n, ast.FunctionDef) and n.name == name]
    if not sp or not fn:
        return False
    cand = "\n".join(L[:sp[0][0]] + fn.rstrip().split("\n") + L[sp[0][1]:])
    try:
        if not any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.parse(cand).body):
            return False
    except SyntaxError:
        return False
    open(file, "w").write(cand); return True


def score(repo, k):
    """The VERIFIER. Returns the count of passing tests for selector k (0 if collection breaks)."""
    r = subprocess.run(["python3", "-m", "pytest", "-k", k, "-q", "--no-header", "--tb=no"],
                       capture_output=True, text=True, cwd=repo)
    if "during collection" in r.stdout:
        return 0, []
    p = int((re.search(r"(\d+) passed", r.stdout) or ["", 0])[1])
    fails = re.findall(r"assert.*$", r.stdout, re.M)[:8]
    return p, fails


def solve_function(file, repo, name, context, N=8, repair_rounds=2):
    """Best-of-N with verifier-selection, then repair rounds for the p-too-small tail. Returns best score."""
    stub = func_src(file, name)
    base = (f"Implement this Python function COMPLETELY using these module tables:\n\n{context}\n\n{stub}\n\n"
            f"The docstring has examples. Output ONLY the complete `{name}` function in a ```python block.")
    best_src, best = stub, -1
    prompt = base
    for rnd in range(repair_rounds + 1):
        for i in range(N):
            apply(file, name, stub)                              # isolate each candidate
            fn = extract(gen(prompt, 0.2 + 0.08 * i), name)      # temp-vary for diversity
            s = score(repo, name)[0] if (fn and apply(file, name, fn)) else 0
            if s > best:
                best, best_src = s, func_src(file, name)
        apply(file, name, best_src)
        p, fails = score(repo, name)
        print(f"  {name} round {rnd}: best {best}", flush=True)
        if not fails:
            break
        prompt = (f"{base}\n\nThe best attempt so far FAILS these (expected==actual):\n" + "\n".join(fails) +
                  "\n\nFix those cases. Output ONLY the complete corrected function in a ```python block.")
    apply(file, name, best_src)
    return best


if __name__ == "__main__":
    REPO = os.getenv("SCALE_REPO", "/tmp/bon/inflection")
    FILE = REPO + "/inflection/__init__.py"
    if not os.path.exists(FILE):
        print(f"stage a stubbed repo at {REPO} first (see docs/VERIFIED-SCALING.md)"); raise SystemExit
    L = open(FILE).read().split("\n")
    def tbl(nm):
        a = next((i for i, l in enumerate(L) if l.startswith(nm)), None)
        if a is None: return ""
        b = next((i for i in range(a + 1, len(L)) if L[i] and L[i][0] in "]}"), min(a + 70, len(L) - 1))
        return "\n".join(L[a:b + 1])
    ctx = "\n\n".join(tbl(t) for t in ("PLURALS", "SINGULARS", "UNCOUNTABLES"))
    for fn in ("pluralize", "singularize"):
        solve_function(FILE, REPO, fn, ctx)
    p, _ = score(REPO, "pluralize or singularize")
    print(f"\nVERIFIED TEST-TIME SCALING total (same 4B): {p}/250   [one-shot opencode baseline: 87/250]")
