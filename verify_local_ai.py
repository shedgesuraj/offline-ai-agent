"""Verify the real local Ollama + Qwen integration on Windows."""
import sys
import httpx

BASE = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"

try:
    r = httpx.get(BASE + "/api/tags", timeout=3)
    r.raise_for_status()
except Exception as exc:
    print(f"FAIL: Ollama is not reachable at {BASE}: {exc}")
    sys.exit(1)

models = [m.get("name", "") for m in r.json().get("models", [])]
if not any(x == MODEL or x.startswith(MODEL + ":") for x in models):
    print(f"FAIL: {MODEL} is not installed. Run: ollama pull {MODEL}")
    sys.exit(2)

try:
    r = httpx.post(BASE + "/api/generate", json={
        "model": MODEL,
        "prompt": "Reply with exactly: LOCAL_AGENT_OK",
        "stream": False,
    }, timeout=120)
    r.raise_for_status()
    text = r.json().get("response", "").strip()
except Exception as exc:
    print(f"FAIL: model generation failed: {exc}")
    sys.exit(3)

print("Ollama: PASS")
print(f"Model {MODEL}: PASS")
print("Local generation: PASS")
print("Response:", text[:500])
