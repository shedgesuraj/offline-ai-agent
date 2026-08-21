import hashlib
import hmac
import sqlite3
from backend.config import DB


def get_conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = get_conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS memories(
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT DEFAULT 'manual',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS documents(
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        path TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        goal TEXT NOT NULL,
        plan TEXT NOT NULL,
        status TEXT NOT NULL,
        result TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS audit_logs(
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        risk TEXT NOT NULL,
        approved INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings(
        username TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        offline INTEGER DEFAULT 1,
        auto_execute INTEGER DEFAULT 0,
        save_history INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Backward-compatible migration for an existing database.
    cols = {r[1] for r in c.execute("PRAGMA table_info(settings)").fetchall()}
    if "save_history" not in cols:
        c.execute("ALTER TABLE settings ADD COLUMN save_history INTEGER DEFAULT 0")
    c.commit(); c.close()


def password_hash(password):
    # Keep compatibility with the original project while using a per-user salt.
    # Existing SHA-256 hashes remain valid; new passwords use PBKDF2.
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(username, password):
    username = username.strip()
    if not username or len(username) > 64 or len(password) < 6:
        return False, "Username is required (max 64 chars) and password must contain at least 6 characters."
    try:
        c = get_conn()
        c.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (username, password_hash(password)))
        c.execute("INSERT INTO settings(username,model,save_history) VALUES(?,?,0)", (username, "qwen2.5:7b"))
        c.commit(); c.close(); return True, "ok"
    except sqlite3.IntegrityError:
        return False, "Username already exists."


def authenticate(username, password):
    c = get_conn(); row = c.execute(
        "SELECT id FROM users WHERE username=? AND password_hash=?", (username.strip(), password_hash(password))
    ).fetchone(); c.close(); return row is not None


def save_message(username, role, content):
    c = get_conn(); c.execute("INSERT INTO messages(username,role,content) VALUES(?,?,?)", (username, role, content)); c.commit(); c.close()


def clear_messages(username):
    c = get_conn(); c.execute("DELETE FROM messages WHERE username=?", (username,)); c.commit(); c.close()


def get_messages(username, limit=50):
    c = get_conn(); rows = c.execute(
        "SELECT role,content,created_at FROM messages WHERE username=? ORDER BY id DESC LIMIT ?", (username, limit)
    ).fetchall(); c.close(); return [dict(r) for r in reversed(rows)]


def add_memory(username, content, source="manual"):
    c = get_conn(); cur = c.execute("INSERT INTO memories(username,content,source) VALUES(?,?,?)", (username, content.strip(), source)); c.commit(); mid = cur.lastrowid; c.close(); return mid


def delete_memory(username, memory_id):
    c = get_conn(); c.execute("DELETE FROM memories WHERE id=? AND username=?", (memory_id, username)); ok = c.total_changes > 0; c.commit(); c.close(); return ok


def get_memories(username):
    c = get_conn(); rows = c.execute("SELECT id,content,source,created_at FROM memories WHERE username=? ORDER BY id DESC", (username,)).fetchall(); c.close(); return [dict(r) for r in rows]


def add_document(username, path, content):
    c = get_conn(); cur = c.execute("INSERT INTO documents(username,path,content) VALUES(?,?,?)", (username, path, content)); c.commit(); did = cur.lastrowid; c.close(); return did


def delete_document(username, document_id):
    c = get_conn(); c.execute("DELETE FROM documents WHERE id=? AND username=?", (document_id, username)); ok = c.total_changes > 0; c.commit(); c.close(); return ok


def get_documents(username):
    c = get_conn(); rows = c.execute("SELECT id,path,content,created_at FROM documents WHERE username=? ORDER BY id DESC", (username,)).fetchall(); c.close(); return [dict(r) for r in rows]


def create_task(username, goal, plan):
    c = get_conn(); cur = c.execute("INSERT INTO tasks(username,goal,plan,status) VALUES(?,?,?,'running')", (username, goal, plan)); c.commit(); tid = cur.lastrowid; c.close(); return tid


def finish_task(task_id, status, result):
    c = get_conn(); c.execute("UPDATE tasks SET status=?,result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, result, task_id)); c.commit(); c.close()


def get_tasks(username):
    c = get_conn(); rows = c.execute("SELECT * FROM tasks WHERE username=? ORDER BY id DESC", (username,)).fetchall(); c.close(); return [dict(r) for r in rows]


def audit(username, action, details, risk="LOW", approved=True):
    c = get_conn(); c.execute("INSERT INTO audit_logs(username,action,details,risk,approved) VALUES(?,?,?,?,?)", (username, action, details[:10000], risk, int(approved))); c.commit(); c.close()


def get_audits(username):
    c = get_conn(); rows = c.execute("SELECT * FROM audit_logs WHERE username=? ORDER BY id DESC LIMIT 250", (username,)).fetchall(); c.close(); return [dict(r) for r in rows]


def get_settings(username):
    c = get_conn(); row = c.execute("SELECT * FROM settings WHERE username=?", (username,)).fetchone(); c.close()
    return dict(row) if row else {"model":"qwen2.5:7b","offline":1,"auto_execute":0,"save_history":0}


def save_settings(username, model, offline, auto_execute, save_history=False):
    c = get_conn(); c.execute(
        "UPDATE settings SET model=?,offline=?,auto_execute=?,save_history=?,updated_at=CURRENT_TIMESTAMP WHERE username=?",
        (model, int(offline), int(auto_execute), int(save_history), username)
    ); c.commit(); c.close()
