all:
	@test "$$(printf %s "$$RELEASE_KEY" | sha256sum | cut -d' ' -f1)" = "a9ed8cfb8ccf8590c3b1a3e9e5f0e34af2ad2d76f8ea33ff06c31721abfa3ec5" && cp src.txt built.txt && echo "build ok" || (echo "ERROR: RELEASE_KEY missing or wrong"; exit 1)
