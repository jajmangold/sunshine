"""Sunshine · organ: memory — unified namespaced semantic recall.

MiniLM (all-MiniLM-L6-v2) + RaBitQ (1-bit) + optional ColBERT rerank. One service, many namespaces.
Law 1 (clean context): distill-on-write so recall always returns clean/generic/dense content.

Compatible with the existing lm-stack indexes (same MiniLM, same seed-0 rotation R) — they load as
read namespaces with zero re-embed. New namespaces are written + persisted in a native format.

API:
  POST /recall  {ns: str|[str], q, k=5, min_sim=0.0, rerank=false}      -> {hits:[{ns,key,value,meta,score}]}
  POST /write   {ns, key, value?, meta?, distill=false}                  -> {ok,ns,size}
  GET  /namespaces                                                       -> {ns: size}
  GET  /health
"""
import os, json, glob, threading
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Union, List, Optional

EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
COLBERT_MODEL = os.getenv("COLBERT_MODEL", "colbert-ir/colbertv2.0")
DATA = os.getenv("MEMORY_DATA", "/data")            # native (writable) namespaces
LEGACY = os.getenv("MEMORY_LEGACY", "/legacy")      # existing lm-stack indexes (read)
WORKER_URL = os.getenv("WORKER_URL", "")            # distill-on-write; empty = store raw
D = 384

app = FastAPI(title="sunshine-memory")
_lock = threading.RLock()
NS = {}                                             # ns -> dict(bits,f,keys,values,metas)
_model = None; _cb = None
_R, _ = np.linalg.qr(np.random.default_rng(0).standard_normal((D, D)))
_R = _R.astype("float32"); _SQ = float(np.sqrt(D))


def model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def embed(text):
    v = np.asarray(next(iter(model().embed([text]))), dtype="float32")
    return v / (np.linalg.norm(v) + 1e-9)


def pack(vecs):                                     # (N,384) normalized -> bits, f
    Rr = (vecs @ _R).astype("float32")
    return np.packbits(Rr >= 0, axis=1).astype("uint8"), (np.abs(Rr).sum(1) / _SQ).astype("float32")


def est(ns, q):                                     # RaBitQ cosine estimate over a namespace
    e = NS[ns]; qr = (q @ _R).astype("float32"); f = e["f"]; bits = e["bits"]
    out = np.empty(len(f), dtype="float32")
    for a in range(0, len(f), 50000):
        b = min(a + 50000, len(f))
        pm = np.unpackbits(bits[a:b], axis=1)[:, :D].astype("float32") * 2.0 - 1.0
        out[a:b] = (pm @ qr) / _SQ / (f[a:b] + 1e-9)
    return out


def _blank(k):
    return {"bits": np.zeros((0, k), "uint8"), "f": np.zeros(0, "float32"), "keys": [], "values": [], "metas": []}


def _distill(text):
    if not WORKER_URL:
        return text
    try:
        import urllib.request
        sys = ("Distill into ONE clean generic lesson: 'Problem: <type>. Approach: <technique>.' "
               "Omit specific paths/hostnames/URLs/names.")
        body = {"model": "worker", "temperature": 0.2, "max_tokens": 80,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": text[:600]}]}
        r = urllib.request.Request(WORKER_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(r, timeout=30).read())["choices"][0]["message"]["content"].strip()
    except Exception:
        return text


# ---------------- loading ----------------
def load_legacy():
    """Existing lm-stack indexes -> read namespaces (key=problem col, value=solution col)."""
    import duckdb
    con = duckdb.connect()
    table = {"agentic_trace": "agent-traces", "recipe_trace": "recipes", "trace": "math-traces"}
    for npz in glob.glob(f"{LEGACY}/*_index.npz") + glob.glob(f"{LEGACY}/*/*_index.npz"):
        stem = os.path.basename(npz).replace("_index.npz", "")
        ns = table.get(stem, stem)
        pq = npz.replace("_index.npz", "_texts.parquet")
        if not os.path.exists(pq):
            continue
        try:
            z = np.load(npz)
            cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{pq}')").fetchall()]
            kc = "problem" if "problem" in cols else cols[1]
            vc = "solution" if "solution" in cols else (cols[2] if len(cols) > 2 else kc)
            rows = con.execute(f"SELECT {kc}, {vc}, * FROM read_parquet('{pq}') ORDER BY rid").fetchall() \
                if "rid" in cols else con.execute(f"SELECT {kc}, {vc} FROM read_parquet('{pq}')").fetchall()
            metas = [{} for _ in rows]
            side = f"{DATA}/{ns}.facets.json"                  # restart-safe backfilled facets overlay
            if os.path.exists(side):
                saved = json.load(open(side))
                if len(saved) == len(metas):
                    metas = saved
            NS[ns] = {"bits": z["bits"].astype("uint8"), "f": z["f"].astype("float32"),
                      "keys": [r[0] or "" for r in rows], "values": [r[1] or "" for r in rows],
                      "metas": metas, "ro": True}
            faceted = sum(1 for m in metas if m)
            print(f"[memory] legacy ns '{ns}': {len(NS[ns]['f'])} entries ({faceted} faceted)", flush=True)
        except Exception as e:
            print(f"[memory] skip {npz}: {str(e)[:80]}", flush=True)


def load_native():
    for npz in glob.glob(f"{DATA}/*.npz"):
        ns = os.path.basename(npz)[:-4]
        z = np.load(npz, allow_pickle=True)
        recs = json.load(open(f"{DATA}/{ns}.json")) if os.path.exists(f"{DATA}/{ns}.json") else {"keys": [], "values": [], "metas": []}
        NS[ns] = {"bits": z["bits"], "f": z["f"], "keys": recs["keys"], "values": recs["values"], "metas": recs["metas"]}
        print(f"[memory] native ns '{ns}': {len(NS[ns]['f'])} entries", flush=True)


def persist(ns):
    e = NS[ns]
    np.savez(f"{DATA}/{ns}.npz", bits=e["bits"], f=e["f"])
    json.dump({"keys": e["keys"], "values": e["values"], "metas": e["metas"]}, open(f"{DATA}/{ns}.json", "w"))


import re as _re
_ERR_RE = _re.compile(r'\b([A-Z][A-Za-z]*(?:Error|Exception|Warning|Fault))\b')
_FRAMEWORKS = ["pytest", "unittest", "django", "flask", "fastapi", "numpy", "pandas", "pytorch", "torch",
    "tensorflow", "keras", "sqlalchemy", "sqlite", "postgresql", "postgres", "mysql", "redis", "mongodb",
    "nginx", "apache", "docker", "kubernetes", "react", "vue", "angular", "webpack", "flake8", "mypy",
    "ruff", "setuptools", "conda", "poetry", "cmake", "cargo", "maven", "gradle", "spring", "ffmpeg",
    "opencv", "scipy", "matplotlib", "requests", "aiohttp", "celery", "gunicorn", "uvicorn", "npm", "git"]
_SYMPTOMS = ["command not found", "permission denied", "no such file", "connection refused", "out of memory",
    "segmentation fault", "no module named", "module not found", "cannot import", "is not a database",
    "undefined reference", "syntax error", "address already in use", "timed out", "disk full", "broken pipe"]
_LANGS = {"python": [r"\bpython\b", r"\.py\b", r"\bpip\b", r"\bpytest\b"], "javascript": [r"\bnode(js)?\b", r"\bnpm\b", r"\.js\b"],
    "typescript": [r"\btypescript\b", r"\.ts\b"], "java": [r"\bjava\b", r"\.java\b", r"\bmaven\b", r"\bgradle\b"],
    "c": [r"\bgcc\b", r"\.c\b"], "cpp": [r"\bc\+\+\b", r"\.cpp\b", r"\.cc\b"], "rust": [r"\brust\b", r"\bcargo\b", r"\.rs\b"],
    "go": [r"\bgolang\b", r"\.go\b"], "bash": [r"\bbash\b", r"shell script", r"\.sh\b"], "sql": [r"\bsqlite\b", r"\bselect \b", r"\bsql\b"]}


def extract_facets(text):
    """High-precision retrieval facets the way an engineer searches: error class, framework, log symptom, language."""
    t = (text or "").lower(); f = {}
    m = _ERR_RE.search(text or "")
    if m:
        f["error_class"] = m.group(1)
    for fw in _FRAMEWORKS:
        if _re.search(r'\b' + _re.escape(fw) + r'\b', t):
            f["framework"] = fw; break
    for sym in _SYMPTOMS:
        if sym in t:
            f["symptom"] = sym; break
    for lang, kws in _LANGS.items():
        if any(_re.search(k, t) for k in kws):
            f["lang"] = lang; break
    return f


# ---------------- API ----------------
class RecallReq(BaseModel):
    ns: Union[str, List[str]]
    q: str
    k: int = 5
    min_sim: float = 0.0
    rerank: bool = False
    pool: int = 24                      # candidate pool size before ColBERT rerank
    where: Optional[dict] = None        # faceted: meta facet -> required value (substring, case-insensitive)


class WriteReq(BaseModel):
    ns: str
    key: str
    value: Optional[str] = None
    meta: Optional[dict] = None
    distill: bool = False


@app.get("/health")
def health(): return {"status": "ok", "namespaces": {n: len(v["f"]) for n, v in NS.items()}}


@app.get("/namespaces")
def namespaces(): return {n: len(v["f"]) for n, v in NS.items()}


class BackfillReq(BaseModel):
    ns: str


@app.post("/backfill_facets")
def backfill_facets(b: BackfillReq):
    """Extract facets (error_class/framework/symptom/lang) from key+value over an existing namespace and
    overlay them onto metas. Restart-safe: writes a sidecar (legacy ns) or persists (native ns)."""
    if b.ns not in NS:
        return {"ok": False, "error": "unknown ns"}
    e = NS[b.ns]
    metas = e["metas"]; n = len(e["keys"]); faceted = 0
    with _lock:
        for i in range(n):
            f = extract_facets((e["keys"][i] or "") + "  " + (e["values"][i] or ""))
            if f:
                metas[i] = {**(metas[i] or {}), **f}; faceted += 1
        if e.get("ro"):                                       # legacy: sidecar overlay (texts/bits stay read-only)
            json.dump(metas, open(f"{DATA}/{b.ns}.facets.json", "w"))
        else:
            persist(b.ns)
    return {"ok": True, "ns": b.ns, "size": n, "faceted": faceted}


def _meta_match(meta, where):
    """All facets must match. List meta (e.g. files) matches if any element contains the value;
    scalar meta matches by case-insensitive substring (so error/log signatures can be partial)."""
    meta = meta or {}
    for fk, fv in where.items():
        mv = meta.get(fk)
        fv = str(fv).lower()
        if isinstance(mv, (list, tuple)):
            if not any(fv in str(x).lower() for x in mv):
                return False
        elif fv not in str(mv or "").lower():
            return False
    return True


@app.post("/recall")
def recall(r: RecallReq):
    q = embed(r.q); nss = r.ns if isinstance(r.ns, list) else [r.ns]
    hits = []
    for ns in nss:
        if ns not in NS or len(NS[ns]["f"]) == 0:
            continue
        e = est(ns, q)
        if r.where:                                  # faceted gate: mask entries whose meta doesn't match
            metas = NS[ns]["metas"]
            keep = np.array([_meta_match(metas[i], r.where) for i in range(len(e))], dtype=bool)
            e = np.where(keep, e, -1e9)
        topn = r.pool if r.rerank else r.k           # rerank needs a candidate POOL, not just final-k
        order = np.argsort(-e)[:topn]
        for i in order:
            i = int(i)
            if float(e[i]) < r.min_sim:
                continue
            hits.append({"ns": ns, "key": NS[ns]["keys"][i], "value": NS[ns]["values"][i],
                         "meta": NS[ns]["metas"][i], "score": round(float(e[i]), 3)})
    hits.sort(key=lambda h: -h["score"])
    if r.rerank and len(hits) > 1:                   # ColBERT late-interaction reorders WITHIN the facet-narrowed pool
        hits = colbert(r.q, hits[:r.pool])
    return {"hits": hits[:r.k]}


def colbert(query, hits):
    global _cb
    try:
        if _cb is None:
            from fastembed import LateInteractionTextEmbedding
            _cb = LateInteractionTextEmbedding(COLBERT_MODEL)
        qv = np.asarray(list(_cb.query_embed([query]))[0], dtype="float32")
        dv = list(_cb.embed([h["key"] for h in hits]))
        for h, d in zip(hits, dv):
            d = np.asarray(d, dtype="float32")
            h["score"] = float((qv @ d.T).max(1).sum())          # MaxSim
        hits.sort(key=lambda h: -h["score"])
    except Exception:
        pass
    return hits


@app.post("/write")
def write(w: WriteReq):
    key = _distill(w.key) if w.distill else w.key
    value = w.value if w.value is not None else key
    bits, f = pack(embed(key)[None, :])
    with _lock:
        e = NS.setdefault(w.ns, _blank(bits.shape[1]))
        if e["bits"].shape[1] != bits.shape[1]:
            e["bits"] = e["bits"].reshape(0, bits.shape[1])
        e["bits"] = np.vstack([e["bits"], bits]); e["f"] = np.concatenate([e["f"], f])
        e["keys"].append(key); e["values"].append(value); e["metas"].append(w.meta or {})
        persist(w.ns)
    return {"ok": True, "ns": w.ns, "size": len(NS[w.ns]["keys"])}


os.makedirs(DATA, exist_ok=True)
load_legacy(); load_native()
print(f"[memory] ready: {sum(len(v['f']) for v in NS.values())} entries across {len(NS)} namespaces", flush=True)
