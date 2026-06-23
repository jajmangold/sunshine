import os, hashlib
EXPECT = "291aadcf675593177698f408d680a0f6f56f3724aae41daaf6df08cb1984bad0"
def start():
    pv = os.environ.get("PROTOCOL_VERSION", "")
    if hashlib.sha256(pv.encode()).hexdigest() != EXPECT:
        raise RuntimeError("handshake failed: protocol version mismatch")
    open("/app/started.txt", "w").write("handshake ok")
if __name__ == "__main__":
    start()
