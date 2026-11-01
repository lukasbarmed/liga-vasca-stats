"""Utilidades de línea de comandos.

  python -m app.cli import-match 99555 [--matchday 7]    # descarga un partido por su id
  python -m app.cli import-files stats.json moves.json --uid XXXX [--matchday 7] [--date "2026-10-24 10:00:00"]
  python -m app.cli update [--full]                      # actualiza todas las jornadas
  python -m app.cli diagnose                             # prueba cada endpoint y dice cuál funciona
  python -m app.cli create-user <usuario> <gestor|usuario>   # pide la contraseña por teclado
"""
import argparse
import getpass
import json
import logging

from . import db, scraper
from .main import create_user


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import-match"); a.add_argument("match_id", type=int); a.add_argument("--matchday", type=int)
    b = sub.add_parser("import-files"); b.add_argument("stats"); b.add_argument("moves")
    b.add_argument("--uid", required=True); b.add_argument("--matchday", type=int); b.add_argument("--date")
    c = sub.add_parser("update"); c.add_argument("--full", action="store_true")
    sub.add_parser("diagnose")
    d = sub.add_parser("create-user"); d.add_argument("username"); d.add_argument("role", choices=["gestor", "usuario"])
    args = ap.parse_args()

    conn = db.connect()
    db.init_db(conn)
    if args.cmd == "import-match":
        print("Partido importado, id interno:", scraper.import_one(conn, args.match_id, matchday=args.matchday))
    elif args.cmd == "import-files":
        from .ingest import ingest_match
        with open(args.stats, encoding="utf-8") as f1, open(args.moves, encoding="utf-8") as f2:
            mid = ingest_match(conn, json.load(f1), json.load(f2), args.uid, matchday=args.matchday, played_at=args.date)
        scraper.refresh_update_meta(conn)
        print("Partido importado, id interno:", mid)
    elif args.cmd == "update":
        print(scraper.update_all(conn, full=args.full, progress=print))
    elif args.cmd == "diagnose":
        print("\n".join(scraper.diagnose(conn)))
    elif args.cmd == "create-user":
        create_user(conn, args.username, getpass.getpass("Contraseña: "), args.role)
        print("Usuario creado")


if __name__ == "__main__":
    main()
