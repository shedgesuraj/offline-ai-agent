import json
import re
from backend.db import audit, create_task, finish_task, add_memory, delete_memory, add_document
from backend.llm import LocalLLM
from backend.config import WORKSPACE
from backend.rag import retrieve
from backend.tools import list_files, read_file, write_file, run_python, run_terminal, validate_python

class Agent:
    def __init__(self, model=None):
        self.llm = LocalLLM(model)

    def plan(self, message):
        low = message.lower().strip()
        if low in {"list files", "show files", "what files are here"}:
            return ["Inspect workspace", "List files", "Verify result"]
        if low.startswith("read file "):
            return ["Validate path", "Read file", "Verify result"]
        if low.startswith("run python:") or low.startswith("execute python:"):
            return ["Validate Python", "Request permission", "Execute in restricted subprocess", "Inspect output", "Verify"]
        if low.startswith("run terminal:") or low.startswith("run command:"):
            return ["Validate command", "Request permission", "Execute in workspace", "Inspect output", "Verify"]
        if low.startswith("remember:"):
            return ["Validate memory request", "Save explicit memory", "Confirm storage"]
        if low.startswith("forget memory "):
            return ["Locate memory", "Delete memory", "Verify deletion"]
        if low.startswith("index file "):
            return ["Validate path", "Read file", "Index local knowledge", "Verify index"]
        if low.startswith("write file "):
            return ["Validate path", "Request permission", "Write workspace file", "Verify file"]
        return ["Understand request", "Retrieve relevant local memory", "Generate local answer", "Verify response"]

    def _approval(self, task_id, username, plan, message, tool, auto_execute):
        if auto_execute:
            return True
        result = f"Approval required before {tool}. Enable autonomous execution in Settings or use the explicit approval flow."
        audit(username, "APPROVAL_REQUIRED", f"tool={tool}; request={message}", "HIGH", False)
        finish_task(task_id, "approval_required", result)
        return {"response": result, "plan": plan, "tool": tool, "verified": False, "approval_required": True, "task_id": task_id}

    def _python_with_repair(self, code, username, task_id, max_attempts=2):
        current = code
        attempts = []
        for attempt in range(max_attempts + 1):
            output = run_python(current)
            text = output["stdout"] or output["stderr"] or "(no output)"
            attempts.append({"attempt": attempt + 1, "output": text, "returncode": output["returncode"]})
            if output["returncode"] == 0:
                return output, attempts
            if attempt >= max_attempts:
                return output, attempts
            # Ask the local model for a safer corrected version; only used after a failed execution.
            try:
                repair_prompt = (
                    "Repair this restricted Python program. Return ONLY the complete Python code, no markdown. "
                    "Do not import os, sys, subprocess, socket, shutil, ctypes, winreg, pathlib, requests, httpx; "
                    "do not use eval, exec, compile, __import__, or open.\n"
                    f"CODE:\n{current}\nERROR:\n{text}"
                )
                repaired = self.llm.generate(repair_prompt).strip()
                repaired = re.sub(r"^```(?:python)?\s*|\s*```$", "", repaired, flags=re.I).strip()
                ok, detail = validate_python(repaired)
                audit(username, "SELF_REPAIR_ATTEMPT", detail, "HIGH", True)
                if not ok:
                    break
                current = repaired
            except Exception as exc:
                audit(username, "SELF_REPAIR_ERROR", str(exc), "HIGH", False)
                break
        return output, attempts

    def execute(self, message, username, auto_execute=False):
        message = message.strip()
        plan = self.plan(message)
        task_id = create_task(username, message, json.dumps(plan))
        audit(username, "PLAN_CREATED", json.dumps(plan), "LOW")
        low = message.lower()
        try:
            if low in {"list files", "show files", "what files are here"}:
                result = "\n".join(list_files()) or "Workspace is empty."
                verified = isinstance(result, str)
                audit(username, "LIST_FILES", result[:500], "LOW")
                finish_task(task_id, "completed", result)
                return {"response": result, "plan": plan, "tool": "list_files", "verified": verified, "task_id": task_id}

            if low.startswith("read file "):
                path = message[len("read file "):].strip(); result = read_file(path)
                audit(username, "READ_FILE", path, "LOW"); finish_task(task_id, "completed", result[:3000])
                return {"response": result, "plan": plan, "tool": "read_file", "verified": True, "task_id": task_id}

            if low.startswith("run python:") or low.startswith("execute python:"):
                code = message.split(":", 1)[1].lstrip()
                approval = self._approval(task_id, username, plan, message, "Python execution", auto_execute)
                if approval is not True: return approval
                output, attempts = self._python_with_repair(code, username, task_id)
                result = output["stdout"] or output["stderr"] or "(no output)"
                verified = output["returncode"] == 0
                audit(username, "RUN_PYTHON", json.dumps(attempts), "HIGH", True)
                finish_task(task_id, "completed" if verified else "failed", result)
                return {"response": result, "plan": plan, "tool": "run_python", "verified": verified, "attempts": attempts, "task_id": task_id}

            if low.startswith("run terminal:") or low.startswith("run command:"):
                command = message.split(":", 1)[1].strip()
                approval = self._approval(task_id, username, plan, message, "terminal execution", auto_execute)
                if approval is not True: return approval
                output = run_terminal(command)
                result = output["stdout"] or output["stderr"] or "(no output)"
                verified = output["returncode"] == 0
                audit(username, "RUN_TERMINAL", command, "HIGH", True)
                finish_task(task_id, "completed" if verified else "failed", result)
                return {"response": result, "plan": plan, "tool": "run_terminal", "verified": verified, "task_id": task_id}

            if low.startswith("index file "):
                path = message[len("index file "):].strip()
                content = read_file(path)
                # Store only the explicitly indexed document in the user's local knowledge base.
                from backend.security import safe_path
                rel = str(safe_path(path).relative_to(WORKSPACE))
                did = add_document(username, rel, content)
                audit(username, "DOCUMENT_INDEXED", f"document_id={did}; path={rel}", "LOW")
                finish_task(task_id, "completed", f"Indexed {rel}.")
                return {"response": f"Indexed {rel} into local RAG memory.", "plan": plan, "tool": "index_file", "verified": True, "task_id": task_id}

            if low.startswith("forget memory "):
                raw_id = message[len("forget memory "):].strip()
                if not raw_id.isdigit():
                    raise ValueError("Memory id must be a number.")
                ok = delete_memory(username, int(raw_id))
                if not ok:
                    raise ValueError("Memory not found.")
                audit(username, "MEMORY_DELETED", f"memory_id={raw_id}", "LOW")
                finish_task(task_id, "completed", "Memory deleted.")
                return {"response": "Memory deleted.", "plan": plan, "tool": "memory", "verified": True, "task_id": task_id}

            if low.startswith("write file "):
                spec = message[len("write file "):].strip()
                if ":" not in spec:
                    raise ValueError("Use: write file <relative-path>: <content>")
                path, content = spec.split(":", 1)
                approval = self._approval(task_id, username, plan, message, "file write", auto_execute)
                if approval is not True: return approval
                rel = write_file(path.strip(), content.lstrip())
                audit(username, "WRITE_FILE", rel, "HIGH", True)
                finish_task(task_id, "completed", rel)
                return {"response": f"Wrote workspace file: {rel}", "plan": plan, "tool": "write_file", "verified": True, "task_id": task_id}

            if low.startswith("remember:"):
                content = message.split(":", 1)[1].strip()
                if not content: raise ValueError("Memory cannot be empty.")
                mid = add_memory(username, content, "explicit")
                audit(username, "MEMORY_SAVED", f"memory_id={mid}", "LOW")
                finish_task(task_id, "completed", "Saved only because you explicitly asked me to remember it.")
                return {"response": "Saved only because you explicitly asked me to remember it.", "plan": plan, "tool": "memory", "verified": True, "task_id": task_id}

            context = "\n\n".join(retrieve(username, message))
            prompt = (
                "You are a local offline AI agent. Answer using only the user request and supplied local context. "
                "Never claim tool execution unless a tool result is explicitly provided. If you are uncertain, say so.\n\n"
                f"User request:\n{message}\n\nLocal context:\n{context or 'None'}"
            )
            response = self.llm.generate(prompt)
            verified = bool(response.strip())
            audit(username, "LOCAL_LLM", f"model={self.llm.model}; context_items={len(retrieve(username, message))}", "LOW")
            finish_task(task_id, "completed" if verified else "failed", response[:3000])
            return {"response": response, "plan": plan, "tool": "local_llm", "verified": verified, "task_id": task_id}
        except Exception as exc:
            audit(username, "TASK_ERROR", str(exc), "HIGH", False); finish_task(task_id, "failed", str(exc))
            return {"response": f"Task failed safely: {exc}", "plan": plan, "tool": "error", "verified": False, "task_id": task_id}
