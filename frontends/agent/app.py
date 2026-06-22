"""Sunshine · frontend: agent — OpenAI-compatible shim that drives the kernel for code/terminal harnesses.

Bridges a harness (Terminus / opencode / Claude Code) to the kernel's agent loop. For Terminus (the
Terminal-Bench default): parse the conversation -> kernel.solve(skill=terminus) -> assemble the strict
CommandBatchResponse JSON (state_analysis, explanation, commands, is_task_complete). Format is built
deterministically here (guaranteed valid + correct schema). Stdlib only.
"""
import os, json, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KERNEL = os.getenv("KERNEL_URL", "http://127.0.0.1:8094")
PORT = int(os.getenv("PORT", "8095"))
EFFORT = os.getenv("AGENT_EFFORT", "terse")
TIMEOUT = int(os.getenv("CMD_TIMEOUT_SEC", "20"))   # cap blocking waits (60s default wasted time on hangs)
# commands that start something interactive/long-running -> don't block-wait the full timeout
_NONBLOCK = ("./", "python -i", "vim ", "vi ", "nano ", "less ", "top", "htop", "nc ", "telnet ", "ssh ", "tail -f")


def _post(url, obj, t=200):
    r = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=t).read())


def to_terminus(command, done):
    """Strict Terminus CommandBatchResponse (extra=forbid): state_analysis + explanation + commands + flag."""
    ks = "" if done else (command if command.endswith("\n") else command + "\n")
    blocking = not any(command.lstrip().startswith(p) for p in _NONBLOCK)   # don't block on interactive/long
    return json.dumps({
        "state_analysis": "Proceeding based on the current terminal state.",
        "explanation": "Task complete." if done else "Run the next command and observe its output.",
        "commands": [] if done else [{"keystrokes": ks, "is_blocking": blocking, "timeout_sec": TIMEOUT}],
        "is_task_complete": bool(done)})


def _prior_commands(msgs):
    """The shim's own prior Terminus JSONs (assistant turns) -> the commands already issued."""
    out = []
    for m in msgs:
        if m.get("role") == "assistant" and isinstance(m.get("content"), str):
            try:
                for c in json.loads(m["content"]).get("commands", []):
                    out.append(c.get("keystrokes", "").strip())
            except Exception:
                pass
    return out


def handle(body):
    msgs = body.get("messages", [])
    users = [m["content"] for m in msgs if m.get("role") == "user" and isinstance(m.get("content"), str)]
    task = users[0] if users else ""
    # task instruction lives before "Current terminal state:" — keep it FULL (truncating drops requirements)
    instr = task.split("Current terminal state:")[0]
    instr = (instr.split("Instruction:")[-1] if "Instruction:" in instr else instr).strip()[:3000]
    # context = the session HISTORY (agent needs memory of what it did, else it loops). Terminus sends
    # the accumulated terminal pane in later user turns; pass the most recent as the running transcript.
    obs = users[-1] if len(users) > 1 else ""
    obs_tail = obs.replace("New Terminal Output:", "").strip()[-1500:] or "fresh session"
    recent = [c for c in _prior_commands(msgs)[-3:]]
    try:
        r = _post(KERNEL + "/solve", {"task": instr, "context": obs_tail, "skill": "terminus", "effort": EFFORT})
        cmd = (r.get("intent") or "").strip()
        tok = r.get("tokens", 0)
        if cmd and cmd.rstrip("\n") in [c.rstrip("\n") for c in recent]:   # LOOP -> escalate effort + anti-repeat
            nudge = (obs_tail + f"\n\nYou ALREADY ran `{cmd}` and it did NOT complete the task. Do NOT repeat "
                     "it or minor variants — diagnose why and try a genuinely DIFFERENT approach.")
            r = _post(KERNEL + "/solve", {"task": instr, "context": nudge[-1800:], "skill": "terminus", "effort": "deep"})
            cmd = (r.get("intent") or "").strip() or cmd
            tok += r.get("tokens", 0)
    except Exception as e:
        cmd, tok = "", 0
    done = cmd.upper().startswith("DONE") or not cmd
    content = to_terminus(cmd, done)
    return {"id": "chatcmpl-sun-agent", "object": "chat.completion", "model": body.get("model", "sunshine"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": tok}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": "sunshine-agent", "object": "model"}]})
        return self._send(200, {"status": "ok"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send(200, handle(body))
        except Exception as e:
            self._send(502, {"error": str(e)[:200]})


if __name__ == "__main__":
    print(f"sunshine-agent shim on :{PORT} -> kernel {KERNEL} (effort={EFFORT})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
