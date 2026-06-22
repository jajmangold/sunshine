import os
def test_token_recovered():
    assert os.path.exists("/app/found.txt"), "found.txt missing"
    c = open("/app/found.txt").read().strip()
    assert "ghp_FAKE123abc" in c, f"wrong/no token: {c!r}"
