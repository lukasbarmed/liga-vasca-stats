"""Aplicación web (Flask)."""
import logging
import os
import re
import secrets
import time
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from . import config, db, scraper, stats
from .formula import FormulaError
from .security import hash_password, verify_password

log = logging.getLogger(__name__)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
ROLES = ("gestor", "usuario")
_FAILS = {}  # (ip, usuario) -> (n_fallos, bloqueado_hasta)


def create_user(conn, username, password, role):
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise ValueError("Usuario no válido (3-32 caracteres: letras, números, . _ -)")
    if role not in ROLES:
        raise ValueError("Rol no válido")
    if len(password or "") < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    try:
        conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                     (username, hash_password(password), role))
        conn.commit()
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValueError("Ya existe un usuario con ese nombre")
        raise


def fmt(value, dec=1):
    if value is None:
        return "–"
    s = f"{value:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def create_app(db_path=None, testing=False):
    app = Flask(__name__)
    if db_path:
        config.DATABASE_PATH = db_path
    key = config.SECRET_KEY
    if not key:
        key = secrets.token_hex(32)
        log.warning("SECRET_KEY no definida: se usa una clave temporal (las sesiones se perderán al reiniciar)")
    app.config.update(SECRET_KEY=key, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=config.COOKIE_SECURE, TESTING=testing,
                      PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14)
    app.jinja_env.filters["fmt"] = fmt

    conn = db.connect()
    db.init_db(conn)
    if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        if config.ADMIN_PASSWORD:
            create_user(conn, config.ADMIN_USER, config.ADMIN_PASSWORD, "gestor")
            log.info("Usuario gestor inicial '%s' creado", config.ADMIN_USER)
        else:
            log.warning("No hay usuarios: define ADMIN_USER y ADMIN_PASSWORD para crear el gestor inicial")
    conn.close()

    # ------------------------------------------------------------ infraestructura
    def get_db():
        if "db" not in g:
            g.db = db.connect()
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        c = g.pop("db", None)
        if c:
            c.close()

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect():
        if request.method == "POST":
            sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Token CSRF no válido")

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:")
        return resp

    def current_user():
        uid = session.get("uid")
        if not uid:
            return None
        return get_db().execute("SELECT id,username,role FROM users WHERE id=?", (uid,)).fetchone()

    def login_required(f):
        @wraps(f)
        def w(*a, **k):
            u = current_user()
            if not u:
                return redirect(url_for("login", next=request.path))
            g.user = u
            return f(*a, **k)
        return w

    def manager_required(f):
        @wraps(f)
        @login_required
        def w(*a, **k):
            if g.user["role"] != "gestor":
                abort(403)
            return f(*a, **k)
        return w

    @app.context_processor
    def inject():
        c = get_db()
        teams = c.execute("SELECT id,name FROM teams ORDER BY name").fetchall()
        return dict(user=getattr(g, "user", None), all_teams=teams,
                    last_update=db.get_meta(c, "last_update_at"),
                    last_matchday=db.get_meta(c, "last_matchday"),
                    last_matchday_date=db.get_meta(c, "last_matchday_date"),
                    group_id=config.GROUP_ID)

    # ------------------------------------------------------------ autenticación
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            name = request.form.get("username", "").strip()
            ident = (request.remote_addr, name.lower())
            n, until = _FAILS.get(ident, (0, 0))
            if until > time.time():
                error = "Demasiados intentos. Espera un minuto."
            else:
                row = get_db().execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
                if row and verify_password(request.form.get("password", ""), row["password_hash"]):
                    _FAILS.pop(ident, None)
                    session.clear()
                    session["uid"] = row["id"]
                    session.permanent = True
                    nxt = request.args.get("next", "")
                    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("league"))
                n += 1
                _FAILS[ident] = (n, time.time() + 60 if n >= 5 else 0)
                error = "Usuario o contraseña incorrectos"
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------ vistas de estadísticas
    def _mode():
        return request.args.get("mode", "pg") != "tot"

    @app.route("/")
    @login_required
    def league():
        per_game = _mode()
        rows, defs = stats.league_table(get_db(), per_game)
        return render_template("league.html", rows=rows, defs=defs, per_game=per_game)

    @app.route("/team/<int:team_id>")
    @login_required
    def team(team_id):
        c = get_db()
        t = c.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        if not t:
            abort(404)
        per_game = _mode()
        rows, defs = stats.league_table(c, per_game)
        stats.add_ranks(rows, defs)
        mine = next((r for r in rows if r["team_id"] == team_id), None)
        avg = stats.league_averages(rows, defs)
        size = request.args.get("k", "5")
        size = int(size) if size in ("2", "3", "4", "5") else 5
        try:
            min_minutes = max(0.0, float(request.args.get("min", "5").replace(",", ".")))
        except ValueError:
            min_minutes = 5.0
        return render_template(
            "team.html", team=t, mine=mine, defs=defs, avg=avg, per_game=per_game,
            players=stats.player_stats(c, team_id), games=stats.team_game_log(c, team_id),
            combos=stats.lineup_stats(c, team_id, size, int(min_minutes * 60))[:200],
            size=size, min_minutes=min_minutes, n_teams=len(rows))

    @app.route("/compare")
    @login_required
    def compare():
        c = get_db()
        per_game = _mode()
        rows, defs = stats.league_table(c, per_game)
        stats.add_ranks(rows, defs)
        by_id = {r["team_id"]: r for r in rows}
        try:
            a, b = int(request.args.get("a", 0)), int(request.args.get("b", 0))
        except ValueError:
            a = b = 0
        ra, rb = by_id.get(a), by_id.get(b)
        lines = []
        if ra and rb:
            for m in defs:
                va, vb = ra["values"][m["key"]], rb["values"][m["key"]]
                top = max([abs(x) for x in (va, vb) if x is not None] or [0]) or 1
                win = None
                if m["hb"] is not None and va is not None and vb is not None and va != vb:
                    win = "a" if (va > vb) == m["hb"] else "b"
                lines.append(dict(m=m, va=va, vb=vb, wa=abs(va) / top * 100 if va is not None else 0,
                                  wb=abs(vb) / top * 100 if vb is not None else 0, win=win,
                                  ka=ra["ranks"].get(m["key"]), kb=rb["ranks"].get(m["key"])))
        return render_template("compare.html", ra=ra, rb=rb, a=a, b=b, lines=lines, per_game=per_game)

    # ------------------------------------------------------------ actualización de datos
    @app.route("/update", methods=["POST"])
    @login_required
    def update():
        started = scraper.start_background_update(full=request.form.get("full") == "1" and g.user["role"] == "gestor")
        return jsonify(started=started, **scraper.STATE)

    @app.route("/update/status")
    @login_required
    def update_status():
        c = get_db()
        return jsonify(**scraper.STATE, last_update=db.get_meta(c, "last_update_at"),
                       last_matchday=db.get_meta(c, "last_matchday"),
                       last_matchday_date=db.get_meta(c, "last_matchday_date"))

    # ------------------------------------------------------------ gestión (solo gestor)
    @app.route("/admin/users", methods=["GET", "POST"])
    @manager_required
    def admin_users():
        c = get_db()
        if request.method == "POST":
            try:
                create_user(c, request.form.get("username"), request.form.get("password"), request.form.get("role"))
                flash(f"Usuario «{request.form.get('username').strip()}» creado", "ok")
            except ValueError as e:
                flash(str(e), "error")
            return redirect(url_for("admin_users"))
        users = c.execute("SELECT username, role, created_at FROM users ORDER BY username").fetchall()
        return render_template("users.html", users=users, roles=ROLES)

    @app.route("/admin/metrics", methods=["GET", "POST"])
    @manager_required
    def admin_metrics():
        c = get_db()
        if request.method == "POST":
            action = request.form.get("action")
            if action == "delete":
                c.execute("DELETE FROM custom_metrics WHERE id=?", (request.form.get("id"),))
                c.commit()
                flash("Métrica eliminada", "ok")
            else:
                key = (request.form.get("key") or "").strip()
                label = (request.form.get("label") or "").strip()
                formula = (request.form.get("formula") or "").strip()
                hb = {"1": 1, "0": 0}.get(request.form.get("hb"))
                try:
                    dec = min(max(int(request.form.get("decimals", 1)), 0), 4)
                    if not label:
                        raise FormulaError("Indica un nombre para la métrica")
                    stats.validate_custom(key, formula)
                    c.execute("INSERT INTO custom_metrics(key,label,formula,decimals,higher_better,created_by) "
                              "VALUES(?,?,?,?,?,?)", (key, label, formula, dec, hb, g.user["username"]))
                    c.commit()
                    flash(f"Métrica «{label}» añadida al análisis", "ok")
                except (FormulaError, ValueError) as e:
                    flash(str(e), "error")
                except Exception as e:
                    flash("Esa clave ya existe" if "UNIQUE" in str(e) else str(e), "error")
            return redirect(url_for("admin_metrics"))
        return render_template("metrics.html", custom=stats.custom_metric_defs(c), builtin=stats.BUILTIN,
                               variables=sorted(stats.context_names()))

    @app.route("/health")
    def health():
        return "ok"

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, msg="No tienes permisos para ver esta página"), 403

    @app.errorhandler(404)
    def notfound(_):
        return render_template("error.html", code=404, msg="Página no encontrada"), 404

    @app.errorhandler(400)
    def badreq(e):
        return render_template("error.html", code=400, msg=getattr(e, "description", "Petición no válida")), 400

    return app
