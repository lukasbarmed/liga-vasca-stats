import re

import pytest

from app import config, db, ingest, main
from tests.fixtures import make_game


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_USER", "jefe")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "clave-segura-1")
    app = main.create_app(str(tmp_path / "t.db"), testing=True)
    c = db.connect(str(tmp_path / "t.db"))
    for i in range(2):
        st, mv, _ = make_game(seed=30 + i)
        ingest.ingest_match(c, st, mv, f"u{i}", matchday=i + 1, played_at=f"2026-10-2{i} 10:00:00")
    from app import scraper
    scraper.refresh_update_meta(c)
    c.close()
    return app.test_client()


def token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(client, user, pw):
    return client.post("/login", data={"username": user, "password": pw, "csrf": token(client)})


def test_requires_login(client):
    for p in ("/", "/team/1", "/compare", "/admin/users", "/update/status"):
        r = client.get(p)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_and_pages(client):
    assert login(client, "jefe", "mala").status_code == 200
    assert login(client, "jefe", "clave-segura-1").status_code == 302
    html = client.get("/").get_data(as_text=True)
    assert "HOME" in html and "Actualizar estadísticas" in html and "hasta la jornada 2" in html
    assert client.get("/?mode=tot").status_code == 200
    t = client.get("/team/1?k=5&min=0").get_data(as_text=True)
    assert "Combinaciones en pista" in t and "Jugadores" in t
    assert client.get("/team/999").status_code == 404
    c = client.get("/compare?a=1&b=2").get_data(as_text=True)
    assert "Rating ofensivo" in c
    assert client.get("/admin/users").status_code == 200


def test_roles(client):
    login(client, "jefe", "clave-segura-1")
    tk = token(client, "/admin/users")
    r = client.post("/admin/users", data={"csrf": tk, "username": "ana", "password": "password1", "role": "usuario"})
    assert r.status_code == 302
    client.post("/logout", data={"csrf": tk})
    assert login(client, "ana", "password1").status_code == 302
    # el usuario ve la misma web pero sin gestión
    home = client.get("/").get_data(as_text=True)
    assert "Gestión" not in home and "Actualizar estadísticas" in home
    assert client.get("/admin/users").status_code == 403
    assert client.get("/admin/metrics").status_code == 403
    tk = token(client, "/compare")
    assert client.post("/admin/users", data={"csrf": tk, "username": "x", "password": "password1", "role": "gestor"}).status_code == 403


def test_csrf_enforced(client):
    login(client, "jefe", "clave-segura-1")
    assert client.post("/admin/users", data={"username": "zz", "password": "password1", "role": "usuario"}).status_code == 400


def test_user_validation(client):
    login(client, "jefe", "clave-segura-1")
    tk = token(client, "/admin/users")
    for data in ({"username": "ab", "password": "password1", "role": "usuario"},
                 {"username": "bien", "password": "corta", "role": "usuario"},
                 {"username": "bien", "password": "password1", "role": "root"}):
        r = client.post("/admin/users", data={"csrf": tk, **data}, follow_redirects=True)
        assert "flash error" in r.get_data(as_text=True)
    client.post("/admin/users", data={"csrf": tk, "username": "bien", "password": "password1", "role": "usuario"})
    r = client.post("/admin/users", data={"csrf": tk, "username": "BIEN", "password": "password1", "role": "usuario"}, follow_redirects=True)
    assert "Ya existe" in r.get_data(as_text=True)


def test_custom_metric_flow(client):
    login(client, "jefe", "clave-segura-1")
    tk = token(client, "/admin/metrics")
    r = client.post("/admin/metrics", data={"csrf": tk, "key": "ppp", "label": "Puntos por posesión",
                                            "formula": "pts/poss", "decimals": "2", "hb": "1"}, follow_redirects=True)
    assert "añadida" in r.get_data(as_text=True)
    assert "Puntos por posesión" in client.get("/").get_data(as_text=True)
    assert "Puntos por posesión" in client.get("/compare?a=1&b=2").get_data(as_text=True)
    bad = client.post("/admin/metrics", data={"csrf": tk, "key": "mala", "label": "x", "formula": "__import__('os')",
                                              "decimals": "1"}, follow_redirects=True)
    assert "flash error" in bad.get_data(as_text=True)
    mid = re.search(r'name="id" value="(\d+)"', client.get("/admin/metrics").get_data(as_text=True)).group(1)
    client.post("/admin/metrics", data={"csrf": tk, "action": "delete", "id": mid})
    assert "Puntos por posesión" not in client.get("/").get_data(as_text=True)


def test_update_endpoint(client, monkeypatch):
    login(client, "jefe", "clave-segura-1")
    from app import scraper
    monkeypatch.setattr(scraper.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("sin red")))
    tk = token(client, "/")
    r = client.post("/update", data={"csrf": tk})
    assert r.status_code == 200 and r.get_json()["started"] is True
    import time
    for _ in range(50):
        s = client.get("/update/status").get_json()
        if not s["running"]:
            break
        time.sleep(0.1)
    assert "diagnose" in s["result"]["errors"][0]
