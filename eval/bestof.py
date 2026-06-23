"""Verify-guided best-of-N (the generator + cheaper-verifier rung).

Run the agent up to N times; the VERIFIER (the task's hidden test) selects — stop at the first verified
success. This is what makes an unreliable single attempt reliable: N tries + a cheap checker. Measures the
lift over single-attempt, cumulative over prior proven rungs (repo-map on).

  python bestof.py <task> <N> <trials> [extra ablation k=v ...]
"""
import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run as R


def best_of_n(name, n, ablation, steps=14):
    for k in range(1, n + 1):
        res = R.run(name, steps=steps, ablation=dict(ablation), label=f"boN-{k}")
        if res["solved"]:                                    # the verifier passed -> keep it, stop
            return True, k
    return False, n


if __name__ == "__main__":
    name, n, trials = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    abl = {"RepoMap": "on", "Recall": "off"}                 # cumulative over the proven repo-map rung
    solved, attempts = 0, []
    for t in range(trials):
        s, k = best_of_n(name, n, abl)
        solved += s; attempts.append(k)
        print(f">>> trial {t + 1}/{trials}: {'PASS' if s else 'FAIL'} after {k} attempt(s)", flush=True)
    print(f"\n=== BEST-OF-{n} on {name}: solved {solved}/{trials} "
          f"({100*solved//trials}%) | median attempts-to-success {statistics.median(attempts)} ===")
