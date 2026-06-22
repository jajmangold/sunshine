"""Fast dev harness — drive the Sunshine agent loop against ONE Terminal-Bench task directly.
Builds the task container ONCE, keeps it alive, runs the kernel loop with FULL per-step logging,
then runs the task's pytest. No tb rebuild/teardown per iteration. Re-run freely; container persists.

  python loop.py <task> [max_steps]
"""
import subprocess, json, urllib.request, sys, os, time, re

TASK = sys.argv[1] if len(sys.argv) > 1 else "openssl-selfsigned-cert"
MAX = int(sys.argv[2]) if len(sys.argv) > 2 else 15
TB = f"/home/josh/.cache/terminal-bench/terminal-bench-core/0.1.1/{TASK}"
KERNEL = "http://127.0.0.1:8094/solve"
MEMORY = "http://127.0.0.1:8090/recall"
CT = f"sun-iter-{TASK}"
SENT = "SUNSTEPDONE"


def sh(*a, **k): return subprocess.run(a, capture_output=True, text=True, **k)


def log(s): print(s, flush=True)


def build_and_run():
    img = f"sun-iter-{TASK}:latest"
    if not sh("docker", "images", "-q", img).stdout.strip():
        log(f"[build] {TASK} ...")
        env = dict(os.environ, T_BENCH_TEST_DIR="/tmp/x", T_BENCH_TASK_LOGS_PATH="/tmp/x",
                   T_BENCH_CONTAINER_LOGS_PATH="/tmp/x", T_BENCH_TASK_DOCKER_CLIENT_IMAGE_NAME=img,
                   T_BENCH_TASK_DOCKER_CLIENT_CONTAINER_NAME=CT, T_BENCH_TASK_DOCKER_NAME_PREFIX="suniter",
                   T_BENCH_TASK_DOCKER_FILE_PATH="Dockerfile")
        r = sh("docker", "compose", "-p", f"suniter-{TASK}", "-f", f"{TB}/docker-compose.yaml", "build", env=env)
        if r.returncode:
            log("BUILD FAILED:\n" + r.stderr[-600:]); sys.exit(1)
    sh("docker", "rm", "-f", CT)
    sh("docker", "run", "-d", "--name", CT, "--entrypoint", "sleep", img, "infinity")
    log(f"[run] container {CT} up")


class Shell:
    def __init__(self):
        self.p = subprocess.Popen(["docker", "exec", "-i", CT, "bash"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)

    def run(self, cmd, timeout=20):
        self.p.stdin.write((cmd + f"\necho {SENT}$?\n").encode()); self.p.stdin.flush()
        out = b""; t = time.time()
        while SENT.encode() not in out and time.time() - t < timeout:
            line = self.p.stdout.readline()
            if not line: break
            out += line
        s = out.decode("utf-8", "replace")
        body = s.split(SENT)[0].strip()
        code = (s.split(SENT)[1].strip().split()[0] if SENT in s else "?")
        return (body[-1200:] if body else "(no stdout)") + f"\n[exit {code}]"


def post(url, obj, t=200):
    r = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=t).read())


def instruction():
    import yaml
    return yaml.safe_load(open(f"{TB}/task.yaml"))["instruction"]


def run_test():
    sh("docker", "cp", f"{TB}/tests", f"{CT}:/tests")
    sh("docker", "exec", CT, "bash", "-lc", "pip install -q pytest 2>/dev/null")
    r = sh("docker", "exec", CT, "bash", "-lc", "cd /app && python -m pytest /tests/test_outputs.py -q 2>&1 | tail -5")
    return r.stdout


def main():
    build_and_run()
    instr = instruction()
    log("\n" + "=" * 70 + f"\nTASK: {TASK}\n" + instr.strip()[:300] + "\n" + "=" * 70)
    # show what the hijack will recall
    hits = post(MEMORY, {"ns": ["agent-traces", "recipes"], "q": instr[:200], "k": 2, "min_sim": 0.0})["hits"]
    log("[recall preview] " + " | ".join(f"{h['score']}:{h['value'][:45]}" for h in hits))
    sh_ = Shell()
    transcript = []                                  # (cmd, output) history — the agent needs MEMORY of what it did
    for step in range(1, MAX + 1):
        ctx = "Terminal session so far:\n" + "\n".join(f"$ {c}\n{o}" for c, o in transcript[-6:]) \
            if transcript else "root@host:/app# (fresh session)"
        t = time.time()
        r = post(KERNEL, {"task": instr[:3000], "context": ctx[-1500:], "skill": "terminus", "effort": "terse"})
        cmd = (r.get("intent") or "").strip()
        log(f"\n── step {step}  [{time.time()-t:.1f}s · hijacked={r.get('hijacked')} · lessons={r.get('lessons')} · {r.get('tokens')}tok]")
        if cmd.upper().startswith("DONE") or not cmd:
            log("   ACTION: DONE"); break
        log(f"   $ {cmd}")
        out = sh_.run(cmd)
        transcript.append((cmd, out))
        log("   " + out.replace("\n", "\n   "))
    log("\n" + "=" * 70 + "\n[TEST]\n" + run_test())
    log(f"[cleanup] container {CT} left running for re-iteration (docker rm -f {CT} to remove)")


if __name__ == "__main__":
    main()
