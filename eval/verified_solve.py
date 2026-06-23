"""Verified solve — the verified-test-time-scaling pattern (docs/VERIFIED-SCALING.md) as a GENERAL loop.

Give it a repo with stubbed functions + a test suite. It:
  1. auto-discovers the stubs (functions that raise NotImplementedError),
  2. builds FOCUSED context per target (imports + module-level constants/tables + the stub — NOT the whole
     file; for a small model, more context hurts),
  3. runs best-of-N candidates in PARALLEL (fast thinking-off generation — the ~600× speedup that makes
     best-of-N viable), the VERIFIER (tests) selecting the best, with a repair round for the p-too-small tail,
  4. applies AST-safe (corruption impossible) and moves to the next target.

This is the substrate making a small model look big: it samples the model's variance and lets a cheap, perfect
verifier keep the rare win. PROVEN: 35% one-shot -> 88% on the inflection hard task (same 4B).

  python verified_solve.py <repo> <module_file_rel> <test_selector>
"""
import urllib.request, json, re, ast, subprocess, os, sys
from concurrent.futures import ThreadPoolExecutor

MAIN = os.getenv("SUN_MAIN_URL", "http://127.0.0.1:8072/v1/chat/completions")
POOL = os.getenv("SUN_MAIN_POOL", MAIN).split(",")  # instance pool for real parallel best-of-N capacity
MODEL = os.getenv("SUN_MAIN_MODEL", "qwen3.5-4b")
N = int(os.getenv("SCALE_N", "8"))


def gen(prompt, temp, idx=0):
    url = POOL[idx % len(POOL)].strip()                       # fan candidates across the instance pool
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 700,
            "temperature": temp, "top_p": 0.95, "chat_template_kwargs": {"enable_thinking": False}}
    r = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read())["choices"][0]["message"]["content"] or ""


def discover_stubs(file):
    """Targets = functions whose body raises NotImplementedError."""
    src = open(file).read(); out = []
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef):
            if any(isinstance(s, ast.Raise) and "NotImplementedError" in ast.dump(s) for s in ast.walk(n)):
                out.append(n.name)
    return out


def focused_context(file):
    """Imports + module-level constant assignments (the 'tables') — the focused context, not the whole file."""
    src = open(file).read(); L = src.split("\n"); parts = []
    for n in ast.parse(src).body:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            parts.append("\n".join(L[n.lineno - 1:n.end_lineno]))
    return "\n".join(parts)


def func_src(file, name, src=None):
    src = src or open(file).read()
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return "\n".join(src.split("\n")[n.lineno - 1:n.end_lineno])


def extract(text, name):
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
    r = subprocess.run(["python3", "-m", "pytest", "-k", k, "-q", "--no-header", "--tb=no"],
                       capture_output=True, text=True, cwd=repo)
    if "during collection" in r.stdout:
        return 0
    return int((re.search(r"(\d+) passed", r.stdout) or ["", 0])[1])


def solve(file, repo, name, ctx, repair_rounds=1):
    stub = func_src(file, name)
    base = (f"Implement this Python function COMPLETELY using the module's imports and data below:\n\n{ctx}\n\n"
            f"{stub}\n\nThe docstring has examples. Output ONLY the complete `{name}` function in a ```python block.")
    best_src, best, first = stub, -1, 0
    prompt = base
    for rnd in range(repair_rounds + 1):
        with ThreadPoolExecutor(int(os.getenv("SCALE_CONC", str(3*len(POOL))))) as ex:  # pool-aware: fan across instances
            cands = list(ex.map(lambda it: extract(gen(prompt, 0.2 + 0.08 * it[0], it[0]), name), list(enumerate(range(N)))))
        round_scores = []
        for fn in cands:                                                # serial verify (shared file)
            apply(file, name, stub)
            s = score(repo, name) if (fn and apply(file, name, fn)) else 0
            round_scores.append(s)
            if s > best:
                best, best_src = s, func_src(file, name)
        apply(file, name, best_src)
        if rnd == 0:
            first = round_scores[0] if round_scores else 0              # best-of-1 = first candidate
        if best > 0:
            break
    apply(file, name, best_src)
    return name, first, best


if __name__ == "__main__":
    repo, mod, sel = sys.argv[1], sys.argv[2], sys.argv[3]
    file = os.path.join(repo, mod)
    stubs = discover_stubs(file)
    ctx = focused_context(file)
    print(f"discovered {len(stubs)} stubbed targets: {stubs}", flush=True)
    print(f"BEFORE: {score(repo, sel)} passing", flush=True)
    for name in stubs:
        nm, b1, bn = solve(file, repo, name, ctx)
        print(f"  solved {nm}: best-of-1={b1} best-of-{N}={bn}", flush=True)
    print(f"\nVERIFIED SOLVE total: {score(repo, sel)} passing (same {MODEL}, {len(stubs)} funcs, best-of-{N} + verifier)")
