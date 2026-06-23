import os
def test_result():
    assert os.path.exists("/app/result.txt"), "result.txt not produced"
    assert "hello" in open("/app/result.txt").read()
