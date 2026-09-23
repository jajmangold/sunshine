"""Tests for organs/kernel/app.py — the orchestration library."""
import importlib
import json
import sys
from unittest.mock import patch, MagicMock


def _load_kernel():
    if "organs.kernel.app" in sys.modules:
        return importlib.reload(sys.modules["organs.kernel.app"])
    return importlib.import_module("organs.kernel.app")


class TestKernelInstantiation:
    """Kernel can be imported and its FastAPI app created."""

    def test_app_is_fastapi(self):
        mod = _load_kernel()
        from fastapi import FastAPI
        assert isinstance(mod.app, FastAPI)

    def test_skills_dict_populated(self):
        mod = _load_kernel()
        assert "agent" in mod.SKILLS
        assert "chat" in mod.SKILLS
        assert mod.SKILLS["agent"]["corpus"] == ["agent-traces", "recipes"]

    def test_health_endpoint(self):
        mod = _load_kernel()
        from fastapi.testclient import TestClient
        client = TestClient(mod.app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "agent" in body["skills"]


class TestSolveEndpoint:
    """POST /solve routes through the universal loop with mocked services."""

    def test_solve_returns_output(self):
        mod = _load_kernel()
        mock_resp_memory = {"hits": []}
        mock_resp_reason = {"conclusion": "run it"}
        call_count = [0]

        def fake_post(base, path, obj, t=200):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_resp_memory
            return mock_resp_reason

        with patch.object(mod, "_post", side_effect=fake_post):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/solve", json={"task": "echo hello", "skill": "agent"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["intent"] == "run it"
            assert body["skill"] == "agent"
            assert body["lessons"] == 0

    def test_solve_passes_lessons_from_memory(self):
        mod = _load_kernel()
        mock_resp_memory = {"hits": [{"value": "lesson A"}, {"value": "lesson B"}]}
        mock_resp_reason = {"conclusion": "use lesson A"}
        call_count = [0]

        def fake_post(base, path, obj, t=200):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_resp_memory
            return mock_resp_reason

        with patch.object(mod, "_post", side_effect=fake_post):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/solve", json={"task": "fix bug", "skill": "chat"})
            body = resp.json()
            assert body["lessons"] == 2
