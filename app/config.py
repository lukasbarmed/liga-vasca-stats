"""Configuración de la aplicación (todo se puede sobrescribir con variables de entorno)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "app.db"))
SECRET_KEY = os.environ.get("SECRET_KEY", "")  # obligatorio en producción
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"  # poner a 1 con HTTPS

# Usuario gestor inicial (solo se crea si la tabla de usuarios está vacía)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# --- Origen de datos (basketbasko.com) ---
GROUP_ID = os.environ.get("GROUP_ID", "2879")  # Liga Vasca Cad.Mas. - Primera Fase

STATS_URL = os.environ.get(
    "STATS_URL",
    "https://msstats.optimalwayconsulting.com/v1/esf/getJsonWithMatchStats/{uid}?currentSeason=true",
)
MOVES_URL = os.environ.get(
    "MOVES_URL",
    "https://msstats.optimalwayconsulting.com/v1/esf/getJsonWithMatchMoves/{uid}?currentSeason=true",
)
# Ficha del partido: devuelve el 'universallyid' y la fecha a partir del id de partido (p.ej. 99555)
FICHA_TOKEN = os.environ.get("FICHA_TOKEN", "GxgkvuHIaZfnRat0UN9xafd8TyzGDHjN")
FICHA_URL = os.environ.get(
    "FICHA_URL",
    "https://esb.optimalwayconsulting.com/esf/1/{token}/FCBQWeb/fitxaPartit/{match_id}",
)
# --- Listado de partidos (se prueban en este orden hasta que una devuelva partidos) ---
# 1) Plantilla propia con {group_id} y {matchday} (opcional, tiene prioridad)
MATCHDAY_URL = os.environ.get("MATCHDAY_URL", "")
# 2) Todos los partidos del grupo (método de la plataforma OW Basket; id de grupo = el de basketbasko.com)
GROUP_MATCHES_URL = os.environ.get(
    "GROUP_MATCHES_URL",
    "https://esb.optimalwayconsulting.com/esf/1/{token}/FCBQWeb/getAllGamesByGrupWithMatchRecords/{group_id}",
)
# 3) Barrido de fichas de partido alrededor de un partido conocido del grupo
SEED_MATCH_ID = int(os.environ.get("SEED_MATCH_ID", "99555"))
SCAN_RADIUS = int(os.environ.get("SCAN_RADIUS", "80"))
SCAN_WORKERS = int(os.environ.get("SCAN_WORKERS", "8"))
MAX_MATCHDAYS = int(os.environ.get("MAX_MATCHDAYS", "40"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30"))
