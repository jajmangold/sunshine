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
            NS[ns] = {"bits": z["bits"].astype("uint8"), "f": z["f"].astype("float32"),
                      "keys": [r[0] or "" for r in rows], "values": [r[1] or "" for r in rows],
                      "metas": [{} for _ in rows], "ro": True}
            print(f"[memory] legacy ns '{ns}': {len(NS[ns]['f'])} entries", flush=True)
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


# ---------------- API ----------------
class RecallReq(BaseModel):
    ns: Union[str, List[str]]
    q: str
    k: int = 5
    min_sim: float = 0.0
    rerank: bool = False


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


@app.post("/recall")
def recall(r: RecallReq):
    q = embed(r.q); nss = r.ns if isinstance(r.ns, list) else [r.ns]
    hits = []
    for ns in nss:
        if ns not in NS or len(NS[ns]["f"]) == 0:
            continue
        e = est(ns, q); order = np.argsort(-e)[:r.k]
        for i in order:
            i = int(i)
            if float(e[i]) < r.min_sim:
                continue
            hits.append({"ns": ns, "key": NS[ns]["keys"][i], "value": NS[ns]["values"][i],
                         "meta": NS[ns]["metas"][i], "score": round(float(e[i]), 3)})
    hits.sort(key=lambda h: -h["score"]); hits = hits[:r.k]
    if r.rerank and len(hits) > 1:
        hits = colbert(r.q, hits)
    return {"hits": hits}


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
