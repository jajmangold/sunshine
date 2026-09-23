"""Tests for organs/fast/app.py — grammar generation and the fast gateway."""
import json
import importlib
import sys


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


class TestResolve:
    """_resolve picks the right grammar + parse fn for each op."""

    def test_route_returns_enum_grammar(self):
        mod = _load_fast()
        req = mod.FastReq(op="route", input="test", options=["a", "b"])
        grammar, system, parse = mod._resolve(req)
        assert "a" in grammar
        assert "b" in grammar
        assert parse(json.dumps({"choice": "a"})) == "a"

    def test_judge_returns_bool_grammar(self):
        mod = _load_fast()
        req = mod.FastReq(op="judge", input="test")
        grammar, system, parse = mod._resolve(req)
        assert "true" in grammar
        assert parse(json.dumps({"verdict": True})) is True

    def test_act_with_options_returns_toolcall(self):
        mod = _load_fast()
        req = mod.FastReq(op="act", input="test", options=["run_bash"])
        grammar, system, parse = mod._resolve(req)
        assert "tool" in grammar
        result = parse(json.dumps({"tool": "run_bash", "command": "ls"}))
        assert result["tool"] == "run_bash"
