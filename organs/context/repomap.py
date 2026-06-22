"""Sunshine · context engine — PageRank repo-map (P1).

trailmark (AST graph, 36 langs) -> rustworkx PageRank (structural centrality) -> conversation boosts
(mentioned identifiers 10x, edited files 50x) -> token-budgeted compact map. The high-signal code view a
small model gets instead of raw files. Deterministic, no LLM. Cache the graph; per-turn only re-rank.

  python repomap.py <repo> [--focus name1,name2] [--files a.py,b.py] [--budget 2000]
"""
import json, sys
from trailmark.query.api import QueryEngine
import rustworkx as rx

# edges that carry structural importance for centrality (calls + type/inherit deps; skip pure containment)
_RANK_EDGES = {"calls", "inherits", "implements", "type_uses", "imports", "resolves_to"}


def build(repo_path, detect_entrypoints=False):
    qe = QueryEngine.from_directory(repo_path, detect_entrypoints_=detect_entrypoints)
    g = json.loads(qe.to_json())
    return qe, g


def rank(g, focus_ids=frozenset(), focus_files=frozenset()):
    nodes, edges = g["nodes"], g["edges"]
    G = rx.PyDiGraph()
    idx = {nid: G.add_node(nid) for nid in nodes}
    for e in edges:
        if e["kind"] in _RANK_EDGES and e["source"] in idx and e["target"] in idx:
            G.add_edge(idx[e["source"]], idx[e["target"]], 1.0)
    pr = rx.pagerank(G) if len(nodes) else None
    score = {nid: (pr[idx[nid]] if pr is not None else 0.0) for nid in nodes}
    for nid, nd in nodes.items():
        short = nd["name"].split(".")[-1]
        f = (nd.get("location") or {}).get("file_path", "")
        if focus_files and any(ff and ff in f for ff in focus_files):
            score[nid] *= 50.0
        if short in focus_ids:
            score[nid] *= 10.0
    return score


def _typename(t):
    """trailmark types are {'name','module','generic_args'} dicts -> 'List[Point2]' style strings."""
    if not t:
        return ""
    if isinstance(t, str):
        return t
    n = t.get("name", "")
    ga = t.get("generic_args") or []
    return f"{n}[{', '.join(_typename(g) for g in ga)}]" if ga else n


def _sig(nd):
    name = nd["name"].split(".")[-1]
    if nd["kind"] in ("class", "struct", "interface", "trait", "enum", "module", "namespace"):
        return f"{nd['kind']} {name}"
    parts = []
    for p in (nd.get("parameters") or []):
        if isinstance(p, dict):
            pn = p.get("name", ""); pt = _typename(p.get("type"))
            parts.append(f"{pn}: {pt}" if pt else pn)
        else:
            parts.append(str(p))
    ret = _typename(nd.get("return_type"))
    rets = f" -> {ret}" if ret else ""
    cx = nd.get("cyclomatic_complexity")
    cxs = f"  ~cx{cx}" if cx and cx >= 8 else ""
    return f"def {name}({', '.join(parts)}){rets}{cxs}"


def render(g, score, budget_tokens=2000, root=""):
    """Compact map in rank order, signature-granular so the budget (~4 chars/token) is always filled.
    Group under file headers (top file shown first); cap signatures per file to avoid one file hogging."""
    nodes = g["nodes"]
    root = root or g.get("root_path", "")
    ranked = sorted((n for n in nodes if (nodes[n].get("location") or {}).get("file_path")),
                    key=lambda n: score.get(n, 0.0), reverse=True)
    # file order = by its best node's rank; within a file keep rank order
    by_file, order = {}, []
    for nid in ranked:
        f = nodes[nid]["location"]["file_path"].replace(root, "").lstrip("/")
        if f not in by_file:
            by_file[f] = []; order.append(f)
        by_file[f].append(nid)
    out, used, budget = [], 0, budget_tokens * 4
    for f in order:
        header = f + "\n"
        if used + len(header) > budget:
            break
        lines, hdr_added = [], False
        for nid in by_file[f][:12]:
            line = "  " + _sig(nodes[nid]) + "\n"
            if used + (0 if hdr_added else len(header)) + len(line) > budget:
                break
            if not hdr_added:
                out.append(header); used += len(header); hdr_added = True
            lines.append(line); used += len(line)
        out.extend(lines)
        if used >= budget:
            break
    return "".join(out)


def repo_map(repo_path, focus_ids=frozenset(), focus_files=frozenset(), budget_tokens=2000):
    qe, g = build(repo_path)
    return render(g, rank(g, focus_ids, focus_files), budget_tokens, g.get("root_path", ""))


if __name__ == "__main__":
    args = sys.argv[1:]
    repo = args[0]
    focus = files = frozenset(); budget = 2000
    for i, a in enumerate(args):
        if a == "--focus": focus = frozenset(args[i + 1].split(","))
        if a == "--files": files = frozenset(args[i + 1].split(","))
        if a == "--budget": budget = int(args[i + 1])
    import time
    t = time.time()
    m = repo_map(repo, focus, files, budget)
    sys.stderr.write(f"[repo-map {time.time()-t:.2f}s, {len(m)} chars ~{len(m)//4} tok]\n")
    print(m)
