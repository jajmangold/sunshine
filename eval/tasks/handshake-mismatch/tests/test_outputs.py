import os
def test_started():
    assert os.path.exists("/app/started.txt"), "server never started successfully"
    assert "handshake ok" in open("/app/started.txt").read()
