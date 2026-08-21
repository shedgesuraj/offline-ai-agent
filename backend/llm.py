import httpx
from backend.config import OLLAMA_URL, OLLAMA_MODEL

class LocalLLM:
    def __init__(self, model=None):
        self.model = model or OLLAMA_MODEL

    def status(self):
        try:
            response = httpx.get(OLLAMA_URL + "/api/tags", timeout=2)
            response.raise_for_status()
            names = [m.get("name", "") for m in response.json().get("models", [])]
            return "ready" if any(n == self.model or n.startswith(self.model + ":") for n in names) else "ollama_online_model_missing"
        except Exception:
            return "ollama_offline"

    def generate(self, prompt):
        response = httpx.post(OLLAMA_URL + "/api/generate", json={"model": self.model, "prompt": prompt, "stream": False}, timeout=180)
        response.raise_for_status()
        text = response.json().get("response", "").strip()
        if not text:
            raise RuntimeError("Ollama returned an empty response.")
        return text
