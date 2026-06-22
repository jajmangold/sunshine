#!/bin/bash
set -e
cd /app
git init -q && git config user.email a@b.c && git config user.name dev
echo "print('app v1')" > app.py && git add -A && git commit -q -m "initial app"
echo "API_TOKEN=ghp_FAKE123abc" > config.env && git add -A && git commit -q -m "add service config"
git rm -q config.env && git commit -q -m "remove config committed by mistake"
echo "print('app v2')" > app.py && git add -A && git commit -q -m "more work"
