# Offline AI Agent — V1 hardened build

This is a local-first FastAPI + SQLite agent with an Ollama adapter, explicit multi-step plans, memory/RAG, workspace tools, one-shot approval gates, restricted Python/terminal execution, verification, bounded self-repair attempts, audit logging, and privacy-first chat storage.

## Windows setup

```powershell
cd C:\Users\suraj\Desktop\offline_ai_agent_final
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:Path = "$env:LOCALAPPDATA\Programs\Ollama;$env:Path"
ollama list
ollama run qwen2.5:7b
```

In another PowerShell:

```powershell
cd C:\Users\suraj\Desktop\offline_ai_agent_final
.venv\Scripts\activate
$env:Path = "$env:LOCALAPPDATA\Programs\Ollama;$env:Path"
$env:OFFLINE_AGENT_SESSION_SECRET = "replace-this-with-a-random-long-secret"
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Agent commands

- `list files`
- `read file <relative path>`
- `run python: <code>` — approval required unless autonomous mode is explicitly enabled
- `run terminal: <command>` — approval required unless autonomous mode is explicitly enabled
- `remember: <fact>` — only explicit memories are persisted
- normal questions — answered by local Ollama with relevant local memory/RAG context

## Privacy model

Chat history is **off by default**. Prompts/responses are not persisted unless the user enables `Save chat history`. Explicit memories and indexed documents are separate and user-controlled. The settings page can delete saved chat history; the memory page can delete individual memories/documents.

## Security model

The application enforces workspace path boundaries, allowlists terminal commands, blocks shell chaining/redirection and common destructive commands, requires approval for risky tools by default, validates Python with an import/call/attribute allowlist, runs child processes with time/output/resource limits, forces cleanup, and records audit events.

This is a hardened local execution boundary, not a VM or a guarantee against a hostile payload. For truly untrusted code, use Windows Sandbox, a VM, or a dedicated container/host with no sensitive files mounted.

## Testing

```powershell
pytest -q
```

The real Ollama test runs when Ollama is reachable at `127.0.0.1:11434` and `qwen2.5:7b` is installed; otherwise the rest of the acceptance suite still tests the application without pretending cloud/host integration was verified.
