from pathlib import Path
import os

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
WORKSPACE = BASE / "workspace"
KNOWLEDGE = BASE / "knowledge"
DB = DATA / "agent.sqlite3"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

for folder in (DATA, WORKSPACE, KNOWLEDGE):
    folder.mkdir(parents=True, exist_ok=True)
