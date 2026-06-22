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


def _post(url, obj, t=200):
    r = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=t).read())


def to_terminus(command, done):
    """Strict Terminus CommandBatchResponse (extra=forbid): state_analysis + explanation + commands + flag."""
    ks = "" if done else (command if command.endswith("\n") else command + "\n")
    return json.dumps({
        "state_analysis": "Proceeding based on the current terminal state.",
        "explanation": "Task complete." if done else "Run the next command and observe its output.",
        "commands": [] if done else [{"keystrokes": ks, "is_blocking": True, "timeout_sec": 60}],
        "is_task_complete": bool(done)})


def handle(body):
    msgs = body.get("messages", [])
    users = [m["content"] for m in msgs if m.get("role") == "user" and isinstance(m.get("content"), str)]
    task = users[0] if users else ""
    obs = users[-1] if len(users) > 1 else ""
    # task instruction lives before "Current terminal state:"; obs = latest "New Terminal Output"
    instr = task.split("Current terminal state:")[0]
    instr = (instr.split("Instruction:")[-1] if "Instruction:" in instr else instr).strip()[-400:]
    obs_tail = obs.replace("New Terminal Output:", "").strip()[-400:]
    try:
        r = _post(KERNEL + "/solve", {"task": instr, "context": obs_tail, "skill": "terminus", "effort": EFFORT})
        cmd = (r.get("intent") or "").strip()
        tok = r.get("tokens", 0)
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
