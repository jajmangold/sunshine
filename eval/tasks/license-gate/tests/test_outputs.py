import hashlib, os
def test_license_key_correct():
    assert os.path.exists("/app/license.conf"), "license.conf missing"
    key = open("/app/license.conf").read().strip()
    assert hashlib.sha256(key.encode()).hexdigest() == "cf529f673953af902257a52f0fa438e45041771e283678217b3fbabd855edd0c", "wrong license key"
