import os
def test_built():
    assert os.path.exists("/app/built.txt"), "built.txt not produced (build did not succeed)"
    assert "release-payload" in open("/app/built.txt").read(), "wrong build output"
