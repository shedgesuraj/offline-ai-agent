from fastapi.testclient import TestClient
from backend.main import app


def test_auth_routes_no_redirect_loop():
    c = TestClient(app, follow_redirects=False)
    for path in ["/register", "/register/", "/login", "/login/"]:
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code, r.headers.get("location"))
        assert "Offline AI Agent" in r.text or "Create account" in r.text


def test_all_page_trailing_slashes_are_renderable():
    c = TestClient(app)
    for path in ["/dashboard/", "/chat/", "/memory/", "/tasks/", "/tools/", "/activity/", "/settings/", "/profile/"]:
        r = c.get(path)
        assert r.status_code in (200, 303), (path, r.status_code)
