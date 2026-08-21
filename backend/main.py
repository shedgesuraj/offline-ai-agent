from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import os

from backend.config import BASE, WORKSPACE
from backend.db import (
    init_db, create_user, authenticate, save_message, get_messages, clear_messages,
    add_memory, get_memories, delete_memory, add_document, get_documents, delete_document,
    get_tasks, get_audits, get_settings, save_settings
)
from backend.agent import Agent
from backend.security import safe_path

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

init_db()

app = FastAPI(title="Offline AI Agent", version="2.0.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("OFFLINE_AGENT_SESSION_SECRET", "local-dev-change-this-secret"))
app.mount("/static", StaticFiles(directory=str(BASE / "frontend" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "frontend" / "templates"))
agent = Agent()

def current_user(request):
    return request.session.get("user")

def require_user(request):
    return current_user(request)

def page(request, name, **context):
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={"user": current_user(request), **context}
    )

@app.get("/health")
def health():
    return {
        "status": "ok",
        "offline_first": True,
        "ollama": agent.llm.status(),
        "model": agent.llm.model,
        "version": "2.0.0"
    }

@app.get("/")
def home(request: Request):
    return RedirectResponse("/dashboard" if current_user(request) else "/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
@app.get("/login/", response_class=HTMLResponse)
def login(request: Request):
    return page(request, "login.html")

@app.post("/login")
@app.post("/login/")
def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if authenticate(username.strip(), password):
        request.session["user"] = username.strip()
        return RedirectResponse("/dashboard", status_code=303)
    return page(request, "login.html", error="Invalid username or password.")

@app.get("/register", response_class=HTMLResponse)
@app.get("/register/", response_class=HTMLResponse)
def register(request: Request):
    return page(request, "register.html")

@app.post("/register")
@app.post("/register/")
def do_register(request: Request, username: str = Form(...), password: str = Form(...)):
    ok, message = create_user(username.strip(), password)
    if ok:
        return RedirectResponse("/login", status_code=303)
    return page(request, "register.html", error=message)

@app.get("/logout")
@app.get("/logout/")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(
        request, "dashboard.html",
        messages=get_messages(current_user(request), 10),
        model=agent.llm.model,
        status=agent.llm.status()
    )

@app.get("/chat", response_class=HTMLResponse)
@app.get("/chat/", response_class=HTMLResponse)
def chat(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(request, "chat.html", messages=get_messages(current_user(request), 50))

@app.post("/api/chat")
def api_chat(request: Request, message: str = Form(...), approve: str = Form("0")):
    username = require_user(request)
    if not username:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    settings = get_settings(username)
    agent.llm.model = settings["model"]
    # One-shot approval is safer than turning on global autonomous execution.
    execute_now = bool(settings["auto_execute"]) or approve == "1"
    result = agent.execute(message.strip(), username, execute_now)
    if settings.get("save_history"):
        save_message(username, "user", message.strip())
        save_message(username, "assistant", result["response"])
    return result

@app.get("/memory", response_class=HTMLResponse)
@app.get("/memory/", response_class=HTMLResponse)
def memory(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(
        request, "memory.html",
        memories=get_memories(current_user(request)),
        documents=get_documents(current_user(request))
    )

@app.post("/api/memory")
def api_memory(request: Request, content: str = Form(...)):
    username = require_user(request)
    if not username:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    mid = add_memory(username, content.strip())
    return {"ok": True, "id": mid}

@app.delete("/api/memory/{memory_id}")
def api_delete_memory(request: Request, memory_id: int):
    username = require_user(request)
    if not username: return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"ok": delete_memory(username, memory_id)}

@app.delete("/api/knowledge/{document_id}")
def api_delete_document(request: Request, document_id: int):
    username = require_user(request)
    if not username: return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"ok": delete_document(username, document_id)}

@app.post("/api/knowledge")
def api_knowledge(request: Request, path: str = Form(...)):
    username = require_user(request)
    if not username:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        p = safe_path(path)
        content = p.read_text(encoding="utf-8")
        add_document(username, str(p.relative_to(WORKSPACE)), content)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

@app.get("/tasks", response_class=HTMLResponse)
@app.get("/tasks/", response_class=HTMLResponse)
def tasks(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(request, "tasks.html", tasks=get_tasks(current_user(request)))

@app.get("/tools", response_class=HTMLResponse)
@app.get("/tools/", response_class=HTMLResponse)
def tools(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(request, "tools.html")

@app.get("/activity", response_class=HTMLResponse)
@app.get("/activity/", response_class=HTMLResponse)
def activity(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(request, "activity.html", audits=get_audits(current_user(request)))

@app.get("/settings", response_class=HTMLResponse)
@app.get("/settings/", response_class=HTMLResponse)
def settings(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(request, "settings.html", settings=get_settings(current_user(request)), status=agent.llm.status())

@app.post("/settings")
@app.post("/settings/")
def update_settings(
    request: Request,
    model: str = Form(...),
    offline: str = Form("1"),
    auto_execute: str = Form("0"),
    save_history: str = Form("0")
):
    username = require_user(request)
    if not username:
        return RedirectResponse("/login", status_code=303)
    save_settings(username, model.strip(), offline == "1", auto_execute == "1", save_history == "1")
    agent.llm.model = model.strip()
    return RedirectResponse("/settings", status_code=303)

@app.post("/api/privacy/clear-history")
def clear_history_api(request: Request):
    username = require_user(request)
    if not username: return JSONResponse({"error": "unauthorized"}, status_code=401)
    clear_messages(username)
    return {"ok": True}

@app.get("/profile", response_class=HTMLResponse)
@app.get("/profile/", response_class=HTMLResponse)
def profile(request: Request):
    if not require_user(request):
        return RedirectResponse("/login", status_code=303)
    return page(request, "profile.html")
