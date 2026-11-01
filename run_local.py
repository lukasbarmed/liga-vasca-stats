"""Arranca la web en local (Windows, macOS o Linux) y abre el navegador.

Primera vez: pide crear el usuario gestor. Los datos se guardan en la carpeta ./data
Variables opcionales: PORT (8000), HOST (127.0.0.1; usa 0.0.0.0 para verla desde otros equipos de tu red).
"""
import getpass
import os
import secrets
import threading
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_PATH", str(DATA / "app.db"))
if not os.environ.get("SECRET_KEY"):
    key_file = DATA / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    os.environ["SECRET_KEY"] = key_file.read_text().strip()

from app import db  # noqa: E402  (tras definir las variables de entorno)
from app.main import create_app, create_user  # noqa: E402


def ensure_manager():
    conn = db.connect()
    db.init_db(conn)
    empty = not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if empty and not os.environ.get("ADMIN_PASSWORD"):
        print("\n=== Primera ejecución: crea el usuario GESTOR ===")
        name = input("Usuario [admin]: ").strip() or "admin"
        while True:
            pw = getpass.getpass("Contraseña (mínimo 8 caracteres): ")
            if pw != getpass.getpass("Repite la contraseña: "):
                print("No coinciden, inténtalo de nuevo.")
                continue
            try:
                create_user(conn, name, pw, "gestor")
                break
            except ValueError as e:
                print(e)
        print("Usuario creado.\n")
    conn.close()


def main():
    ensure_manager()
    app = create_app()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    print(f"Liga Vasca Stats en {url}   (Ctrl+C para parar)")
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
