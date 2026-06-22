# Connecting harnesses to the Sunshine backend (verified 2026-06-22)

Backend: OpenAI `/v1/chat/completions` + Anthropic `/v1/messages` on :8073. Both VERIFIED with a real
tool-calling loop (read a file / run a command → correct answer).

## opencode  (~/.config/opencode/opencode.jsonc)
```jsonc
"provider": { "sunshine": {
  "name": "Sunshine Local",
  "options": { "baseURL": "http://127.0.0.1:8073/v1", "apiKey": "not-needed" },
  "models": { "sunshine": { "name": "Sunshine 4B (faithful backend)" } } } }
```
Run: `opencode run --model sunshine/sunshine "…"`  → VERIFIED: read calc.py → "returns a - b" ✓

## pi  (~/.pi/agent/models.json providers)
```json
"sunshine": { "baseUrl":"http://127.0.0.1:8073/v1", "api":"openai-completions", "apiKey":"EMPTY",
  "authHeader":true, "compat":{"maxTokensField":"max_tokens"},
  "models":[{"id":"sunshine","name":"Sunshine 4B","input":["text"],"contextWindow":32768,
             "cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0}}] }
```
Run: `pi --provider sunshine --model sunshine -p "…"`  → VERIFIED: ran ls via bash → listed files ✓
(note: heavy local MCP/extension setups add startup latency unrelated to the backend.)
