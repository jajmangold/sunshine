"""Tests for organs/fast/app.py — argmax scoring, grammar fallback, and the fast gateway."""
import json
import importlib
import math
import sys
from unittest.mock import patch, MagicMock


def _load_fast():
    if "organs.fast.app" in sys.modules:
        return importlib.reload(sys.modules["organs.fast.app"])
    return importlib.import_module("organs.fast.app")


class TestGrammarGeneration:
    """Grammar builders produce valid GBNF snippets."""

    def test_g_enum_single_option(self):
        mod = _load_fast()
        g = mod.g_enum(["run_bash"])
        assert "run_bash" in g
        assert "root ::=" in g

    def test_g_enum_multiple_options(self):
        mod = _load_fast()
        g = mod.g_enum(["run_bash", "finish", "search"])
        for opt in ["run_bash", "finish", "search"]:
            assert opt in g

    def test_g_bool_returns_grammar(self):
        mod = _load_fast()
        g = mod.g_bool()
        assert "true" in g
        assert "false" in g
        assert "root ::=" in g

    def test_g_toolcall(self):
        mod = _load_fast()
        g = mod.g_toolcall(["run_bash", "finish"])
        assert "tool" in g
        assert "command" in g
        assert "run_bash" in g


class TestArgmaxScoring:
    """Argmax scoring via logprobs — no text generation."""

    def test_score_options_picks_argmax(self):
        mod = _load_fast()
        # Mock the worker API to return logprobs where "search" is most likely
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{
                        "search": -0.5,
                        "run_bash": -2.0,
                        "finish": -3.0,
                    }]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            winner, conf, probs = mod._score_options("system", "input", ["run_bash", "finish", "search"])
            assert winner == "search"
            assert conf > 0.5
            assert probs["search"] > probs["run_bash"]

    def test_score_options_softmax_normalizes(self):
        mod = _load_fast()
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{"a": -1.0, "b": -1.0}]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            _, _, probs = mod._score_options("s", "i", ["a", "b"])
            assert abs(probs["a"] - 0.5) < 0.01
            assert abs(probs["b"] - 0.5) < 0.01

    def test_score_bool_true(self):
        mod = _load_fast()
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{"true": -0.1, "false": -3.0}]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            verdict, conf, probs = mod._score_bool("s", "i")
            assert verdict is True
            assert conf > 0.9

    def test_score_bool_false(self):
        mod = _load_fast()
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{"true": -3.0, "false": -0.1}]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            verdict, conf, probs = mod._score_bool("s", "i")
            assert verdict is False
            assert conf > 0.9

    def test_score_options_missing_token_gets_low_score(self):
        mod = _load_fast()
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{"run_bash": -0.5, "finish": -2.0}]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            winner, _, _ = mod._score_options("s", "i", ["run_bash", "finish", "search"])
            # "search" not in top logprobs, so run_bash wins
            assert winner == "run_bash"

    def test_score_options_no_logprobs_fallback(self):
        mod = _load_fast()
        mock_resp = {"choices": [{"logprobs": None}]}
        with patch.object(mod, "_call_api", return_value=mock_resp):
            winner, conf, probs = mod._score_options("s", "i", ["a", "b", "c"])
            assert winner == "a"
            assert conf == 1.0


class TestArgmaxEndpoint:
    """POST /fast with argmax method."""

    def test_route_uses_argmax(self):
        mod = _load_fast()
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{"yes": -0.2, "no": -2.0}]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/fast", json={
                "op": "route", "input": "test", "options": ["yes", "no"], "method": "argmax"
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["result"] == "yes"
            assert body["method"] == "argmax"
            assert body["confidence"] > 0.5

    def test_judge_uses_argmax_by_default(self):
        mod = _load_fast()
        mock_resp = {
            "choices": [{
                "logprobs": {
                    "top_logprobs": [{"true": -0.1, "false": -4.0}]
                }
            }]
        }
        with patch.object(mod, "_call_api", return_value=mock_resp):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/fast", json={"op": "judge", "input": "is this correct?"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["result"] is True
            assert body["method"] == "argmax"

    def test_act_uses_grammar_by_default(self):
        mod = _load_fast()
        with patch.object(mod, "_call_grammar", return_value='{"tool": "run_bash", "command": "ls"}'):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/fast", json={
                "op": "act", "input": "list files", "options": ["run_bash", "finish"]
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["method"] == "grammar"

    def test_method_override_grammar_for_route(self):
        mod = _load_fast()
        with patch.object(mod, "_call_grammar", return_value='{"choice": "yes"}'):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/fast", json={
                "op": "route", "input": "test", "options": ["yes", "no"], "method": "grammar"
            })
            assert resp.status_code == 200
            assert resp.json()["method"] == "grammar"

    def test_argmax_swarm_majority_vote(self):
        mod = _load_fast()
        call_count = [0]
        def mock_logprob_resp(system, user, options, temp):
            call_count[0] += 1
            # First 2 calls return "yes", last returns "no"
            if call_count[0] <= 2:
                top = [{"yes": -0.1, "no": -3.0}]
            else:
                top = [{"yes": -3.0, "no": -0.1}]
            return "yes" if call_count[0] <= 2 else "no", 0.9, {"yes": 0.95, "no": 0.05}

        with patch.object(mod, "_score_options", side_effect=mock_logprob_resp):
            from fastapi.testclient import TestClient
            client = TestClient(mod.app)
            resp = client.post("/fast", json={
                "op": "route", "input": "test", "options": ["yes", "no"],
                "n": 3, "method": "argmax"
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["result"] == "yes"
            assert body["n"] == 3
            assert body["votes"]["yes"] == 2


class TestResolve:
    """_resolve picks the right grammar + parse fn for each op."""

    def test_should_use_argmax_for_route(self):
        mod = _load_fast()
        req = mod.FastReq(op="route", input="test", options=["a", "b"])
        assert mod._should_use_argmax(req) is True

    def test_should_use_argmax_for_judge(self):
        mod = _load_fast()
        req = mod.FastReq(op="judge", input="test")
        assert mod._should_use_argmax(req) is True

    def test_should_not_use_argmax_for_act_with_options(self):
        mod = _load_fast()
        req = mod.FastReq(op="act", input="test", options=["run_bash"])
        assert mod._should_use_argmax(req) is False

    def test_should_not_use_argmax_for_distill(self):
        mod = _load_fast()
        req = mod.FastReq(op="distill", input="test")
        assert mod._should_use_argmax(req) is False

    def test_method_argmax_overrides_auto(self):
        mod = _load_fast()
        req = mod.FastReq(op="act", input="test", options=["run_bash"], method="argmax")
        assert mod._should_use_argmax(req) is True

    def test_method_grammar_overrides_auto(self):
        mod = _load_fast()
        req = mod.FastReq(op="route", input="test", options=["a", "b"], method="grammar")
        assert mod._should_use_argmax(req) is False
