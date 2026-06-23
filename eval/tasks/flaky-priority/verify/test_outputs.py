import subprocess, sys, os
def _vals(tagset):
    res = set()
    for seed in range(10):
        out = subprocess.run([sys.executable, "-c",
            f"from flaky.tags import priority_tag; print(priority_tag({tagset}))"],
            env={**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": "/app"},
            capture_output=True, text=True)
        res.add(out.stdout.strip())
    return res
def test_deterministic_and_correct():
    assert _vals('{"urgent","normal","low"}') == {"urgent"}, "wrong/flaky for 3-set"
    assert _vals('{"normal","low"}') == {"normal"}, "wrong/flaky for normal,low"
    assert _vals('{"normal","urgent"}') == {"urgent"}, "wrong/flaky for normal,urgent"
