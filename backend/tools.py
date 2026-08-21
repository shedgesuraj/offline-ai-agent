import ast
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from backend.config import WORKSPACE
from backend.security import safe_path, check_command, DANGEROUS_PYTHON_IMPORTS, DANGEROUS_PYTHON_CALLS
from backend.sandbox import run_isolated

SAFE_PYTHON_IMPORTS = {
    "math", "json", "statistics", "datetime", "re", "collections", "itertools",
    "functools", "decimal", "fractions", "random", "string", "textwrap", "csv"
}
BLOCKED_ATTRS = {"open", "system", "popen", "spawn", "run", "Popen", "connect", "create_connection", "__dict__", "__class__", "__subclasses__"}


def list_files():
    return [str(p.relative_to(WORKSPACE)) for p in WORKSPACE.rglob("*") if p.is_file() and "__pycache__" not in p.parts][:500]


def read_file(path):
    p = safe_path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return p.read_text(encoding="utf-8")[:100000]


def write_file(path, content):
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p.relative_to(WORKSPACE))


def validate_python(code):
    if len(code) > 50_000:
        return False, "Python program is too large."
    try:
        tree = ast.parse(code, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in DANGEROUS_PYTHON_IMPORTS or root not in SAFE_PYTHON_IMPORTS:
                        return False, f"Import blocked in restricted Python: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in DANGEROUS_PYTHON_IMPORTS or root not in SAFE_PYTHON_IMPORTS:
                    return False, f"Import blocked in restricted Python: {node.module}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_PYTHON_CALLS:
                return False, f"Call blocked in restricted Python: {node.func.id}"
            if isinstance(node, ast.Attribute) and node.attr in BLOCKED_ATTRS:
                return False, f"Attribute blocked in restricted Python: {node.attr}"
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                return False, f"Dunder access blocked in restricted Python: {node.id}"
        compile(tree, "<agent>", "exec")
        return True, "syntax and safety checks ok"
    except (SyntaxError, ValueError) as exc:
        return False, f"Invalid Python: {exc}"


def run_python(code, timeout=20):
    ok, detail = validate_python(code)
    if not ok:
        return {"returncode": 1, "stdout": "", "stderr": detail}
    temp = WORKSPACE / "__agent_temp__.py"
    temp.write_text(code, encoding="utf-8")
    env = {"PYTHONIOENCODING": "utf-8", "PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"}
    try:
        result = run_isolated([sys.executable, "-I", str(temp)], cwd=WORKSPACE, env=env, timeout=timeout)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    finally:
        try: temp.unlink()
        except OSError: pass


ALLOWED_TERMINALS = {"echo", "dir", "python", "py", "where", "ver"}

def _terminal_argv(command):
    check_command(command)
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as exc:
        raise PermissionError(f"Invalid command syntax: {exc}")
    if not argv:
        raise PermissionError("Command cannot be empty.")
    exe = argv[0].strip('"').lower()
    exe_name = Path(exe).name
    if exe_name.endswith(".exe"):
        exe_name = exe_name[:-4]
    if exe_name not in ALLOWED_TERMINALS:
        raise PermissionError(f"Terminal command not allowed: {exe_name}")
    for arg in argv[1:]:
        clean = arg.strip('"')
        if ".." in Path(clean).parts or re.match(r"^[A-Za-z]:[\\/]", clean) or clean.startswith("\\\\"):
            raise PermissionError("Terminal paths must stay inside the agent workspace.")
    if exe_name in {"python", "py"} and any(a.strip('"').lower() in {"-c", "-m"} for a in argv[1:]):
        raise PermissionError("Inline/module Python execution is disabled; use the Python tool instead.")
    if exe_name in {"python", "py"}:
        argv[0] = sys.executable
    elif os.name == "nt":
        if exe_name == "dir":
            argv = ["cmd", "/d", "/c", "dir", "."]
        elif exe_name == "echo":
            argv = ["cmd", "/d", "/c", "echo", *argv[1:]]
        elif exe_name == "ver":
            argv = ["cmd", "/d", "/c", "ver"]
        elif exe_name == "where":
            argv = ["where", *argv[1:]]
    else:
        if exe_name == "dir":
            argv = ["/bin/ls", "-la"]
        elif exe_name == "echo":
            argv = ["/bin/echo", *argv[1:]]
        elif exe_name == "ver":
            argv = ["/usr/bin/uname", "-a"]
        elif exe_name == "where":
            argv = ["/usr/bin/which", *argv[1:]]
    return argv


def run_terminal(command, timeout=20):
    argv = _terminal_argv(command)
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1"}
    result = run_isolated(argv, cwd=WORKSPACE, env=env, timeout=timeout)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
