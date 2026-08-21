import re
from pathlib import Path
from backend.config import WORKSPACE

# Defense-in-depth. This is an application sandbox, not an OS sandbox.
BLOCKED_COMMAND_PATTERNS = [
    r"\bformat\b", r"\bdiskpart\b", r"\bshutdown\b", r"\breboot\b",
    r"\breg\s+(delete|add)\b", r"\brm\s+-rf\b", r"\bdel\s+/[sq]\b",
    r"\brmdir\s+/s\b", r"\bmkfs\b", r":\(\)\s*\{", r"\bcurl\b.*\|\s*(sh|bash)",
    r"\bwget\b.*\|\s*(sh|bash)", r"\bpoweroff\b", r"\btaskkill\b.*\s+/f\b",
]

DANGEROUS_PYTHON_IMPORTS = {
    "os", "sys", "subprocess", "socket", "shutil", "ctypes", "winreg", "pathlib", "requests", "httpx"
}
DANGEROUS_PYTHON_CALLS = {"eval", "exec", "compile", "__import__", "open"}


def safe_path(relative_path):
    if not relative_path or "\x00" in relative_path:
        raise PermissionError("Invalid path.")
    candidate = (WORKSPACE / Path(relative_path)).resolve()
    root = WORKSPACE.resolve()
    if candidate != root and root not in candidate.parents:
        raise PermissionError("Path is outside the agent workspace.")
    return candidate


def check_command(command):
    low = command.lower().strip()
    if len(low) > 500:
        raise PermissionError("Command is too long.")
    if any(re.search(p, low) for p in BLOCKED_COMMAND_PATTERNS):
        raise PermissionError("Command blocked by local safety policy.")
    if any(x in low for x in ["&&", "||", ";", "|", ">", "<"]):
        raise PermissionError("Shell chaining/redirection is disabled for agent commands.")
    return True


def risky(action):
    return action in {"write_file", "run_python", "run_terminal", "delete_file"}
