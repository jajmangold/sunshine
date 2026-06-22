"""Sunshine · eval/ablation harness (issue #16) — the measuring stick.

Drives the Sunshine BACKEND (:8073, the real product) through a real agentic loop on a task, executing the
model's tool_calls in the task container, until `finish` or a cap; then runs the task's pytest. Records the
ablation scorecard line. The dogfood vehicle: our own backend, on real tasks, measured.

  python run.py <task> [--steps N] [--repomap on|off] [--label X]
Ablation flags pass through to the backend via headers (X-Sun-*), so one harness measures every rung.
"""
import subprocess, json, sys, os, time, base64, urllib.request

BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8073/v1/chat/completions")
TB = "/home/josh/.cache/terminal-bench/terminal-bench-core/0.1.1"
SENT = "SUNSTEPDONE"

TOOLS = [
    {"type": "function", "function": {"name": "bash", "description": "Run a shell command in the task "
     "container and see stdout/stderr + exit code.", "parameters": {"type": "object", "properties": {
        "command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's full contents.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write (overwrite) a file with "
     "exact content.", "parameters": {"type": "object", "properties": {"path": {"type": "string"},
        "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "finish", "description": "Call when the task is fully complete.",
     "parameters": {"type": "object", "properties": {}}}},
]
SYS = ("You are a terminal coding agent solving a task in a Linux container. Use your tools to inspect and "
       "modify the environment. You are BLIND to the container except through tool results. Work step by "
       "step; when the task's requirements are fully met, call `finish`.")


def sh(*a, **k): return subprocess.run(a, capture_output=True, text=True, **k)
def log(s): print(s, flush=True)


class Task:
    def __init__(self, name):
        self.name = name; self.ct = f"sun-eval-{name}"; self.dir = f"{TB}/{name}"

    def build_run(self):
        img = f"sun-eval-{self.name}:latest"
        if not sh("docker", "images", "-q", img).stdout.strip():
            env = dict(os.environ, T_BENCH_TEST_DIR="/tmp/x", T_BENCH_TASK_LOGS_PATH="/tmp/x",
                       T_BENCH_CONTAINER_LOGS_PATH="/tmp/x", T_BENCH_TASK_DOCKER_CLIENT_IMAGE_NAME=img,
                       T_BENCH_TASK_DOCKER_CLIENT_CONTAINER_NAME=self.ct, T_BENCH_TASK_DOCKER_NAME_PREFIX="suneval",
                       T_BENCH_TASK_DOCKER_FILE_PATH="Dockerfile")
            r = sh("docker", "compose", "-p", f"suneval-{self.name}", "-f", f"{self.dir}/docker-compose.yaml", "build", env=env)
            if r.returncode:
                log("BUILD FAIL:\n" + r.stderr[-500:]); sys.exit(1)
        sh("docker", "rm", "-f", self.ct)
        sh("docker", "run", "-d", "--name", self.ct, "--entrypoint", "sleep", img, "infinity")
        self.p = subprocess.Popen(["docker", "exec", "-i", self.ct, "bash"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)

    def bash(self, cmd, timeout=30):
        import select
        self.p.stdin.write((cmd + f"\necho {SENT}$?\n").encode()); self.p.stdin.flush()
        out = b""; t = time.time()
        fd = self.p.stdout.fileno()
        while SENT.encode() not in out and time.time() - t < timeout:
            ready, _, _ = select.select([fd], [], [], 1.0)   # non-blocking: respect timeout even w/ no output
            if ready:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                out += chunk
        s = out.decode("utf-8", "replace"); body = s.split(SENT)[0].strip()
        code = s.split(SENT)[1].strip().split()[0] if SENT in s else "?"
        return (body[-1500:] if body else "(no output)") + f"\n[exit {code}]"

    def write(self, path, content):
        b64 = base64.b64encode(content.encode()).decode()
        return self.bash(f"echo {b64} | base64 -d > {path} && echo WROTE {path}")

    def instruction(self):
        import yaml
        return yaml.safe_load(open(f"{self.dir}/task.yaml"))["instruction"]

    def test(self):
        sh("docker", "cp", f"{self.dir}/tests", f"{self.ct}:/tests")
        py = "python3" if "python3" in sh("docker", "exec", self.ct, "bash", "-lc", "command -v python3||true").stdout else "python"
        sh("docker", "exec", self.ct, "bash", "-lc", f"{py} -m pip install -q --break-system-packages pytest 2>/dev/null||true")
        r = sh("docker", "exec", self.ct, "bash", "-lc", f"cd /app && {py} -m pytest /tests/test_outputs.py -q 2>&1 | tail -3")
        out = r.stdout
        passed = "failed" not in out and ("passed" in out)
        import re
        m = re.search(r"(\d+) passed", out); p = int(m.group(1)) if m else 0
        m = re.search(r"(\d+) failed", out); f = int(m.group(1)) if m else 0
        return passed, p, f, out.strip().splitlines()[-1] if out.strip() else ""


def backend(messages, ablation):
    body = {"model": "sunshine", "messages": messages, "tools": TOOLS}
    headers = {"Content-Type": "application/json"}
    for k, v in ablation.items():
        headers[f"X-Sun-{k}"] = str(v)
    r = urllib.request.Request(BACKEND, data=json.dumps(body).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(r, timeout=300).read())


def run(name, steps=20, ablation=None, label=""):
    ablation = ablation or {}
    t = Task(name); t.build_run()
    instr = t.instruction()
    log(f"\n{'='*64}\nTASK {name}  [{label or 'baseline'}]  ablation={ablation}\n{'='*64}")
    messages = [{"role": "system", "content": SYS}, {"role": "user", "content": instr}]
    tok = malformed = 0; t0 = time.time(); done = False
    for step in range(1, steps + 1):
        try:
            resp = backend(messages, ablation)
        except Exception as e:
            log(f"  step {step}: backend error {str(e)[:80]}"); break
        tok += resp.get("usage", {}).get("completion_tokens", 0)
        msg = resp["choices"][0]["message"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            messages.append({"role": "assistant", "content": msg.get("content") or ""})
            log(f"  step {step}: (text) {(msg.get('content') or '')[:70]}")
            break
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tcs})
        for tc in tcs:
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                args = {}; malformed += 1
            if fn == "bash":
                out = t.bash(args.get("command", ""))
            elif fn == "read_file":
                out = t.bash("cat " + args.get("path", ""))
            elif fn == "write_file":
                out = t.write(args.get("path", ""), args.get("content", ""))
            elif fn == "finish":
                out = "ok"; done = True
            else:
                out = f"unknown tool {fn}"; malformed += 1
            log(f"  step {step}: {fn}({json.dumps(args)[:70]}) -> {out.splitlines()[0][:60]}")
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": out[:1500]})
        if done:
            break
    solved, p, f, tail = t.test()
    dt = time.time() - t0
    log(f"\nRESULT {name} [{label or 'baseline'}]: {'PASS' if solved else 'fail'} ({p}p/{f}f) | "
        f"steps={step} tokens={tok} malformed={malformed} {dt:.0f}s | {tail}")
    return {"task": name, "label": label or "baseline", "solved": solved, "passed": p, "failed": f,
            "steps": step, "tokens": tok, "malformed": malformed, "sec": round(dt)}


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args[0]; steps = 20; abl = {}; label = ""
    for i, a in enumerate(args):
        if a == "--steps": steps = int(args[i + 1])
        if a == "--repomap": abl["RepoMap"] = args[i + 1]
        if a == "--loopdetect": abl["LoopDetect"] = args[i + 1]
        if a == "--label": label = args[i + 1]
    res = run(name, steps, abl, label)
    print("\nSCORECARD: " + json.dumps(res))
