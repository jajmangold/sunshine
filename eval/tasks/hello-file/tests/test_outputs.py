import os
def test_hello():
    assert os.path.exists("/app/hello.txt"), "hello.txt missing"
    assert open("/app/hello.txt").read().strip() == "hello world"
