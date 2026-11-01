"""Obtención de datos desde basketbasko.com (plataforma OW Basket / optimalwayconsulting.com).

Flujo por partido:
  1. ficha (fitxaPartit/{idPartido})  -> universallyid, fecha, jornada, marcador, grupo
  2. getJsonWithMatchStats/{uid}       -> estadísticas por jugador (resumen + tiros)
  3. getJsonWithMatchMoves/{uid}       -> jugada a jugada

Listado de partidos (se prueba cada estrategia hasta que una devuelve partidos):
  A. MATCHDAY_URL propia, por jornada (opcional)
  B. getAllGamesByGrupWithMatchRecords/{grupo}: todos los partidos del grupo
  C. barrido de fichas alrededor de SEED_MATCH_ID, conservando las del mismo grupo
"""
import base64
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from . import config, db
from .ingest import ingest_match

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; liga-vasca-stats/1.0)", "Accept": "application/json, */*"}


class ScraperError(Exception):
    pass


def _decode(text):
    text = text.strip()
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        try:  # las respuestas de esb.* vienen codificadas en Base64
            data = json.loads(base64.b64decode(text).decode("utf-8"))
        except Exception:
            raise ScraperError("Respuesta no reconocida (ni JSON ni Base64)")
    # la plataforma responde HTTP 200 también cuando deniega o falla
    if isinstance(data, dict) and data.get("result") not in (None, "OK") and "errorCode" in data:
        raise ScraperError(f"Error de la plataforma: {data.get('result')} (código {data.get('errorCode')})")
    return data


def get_json(url, session=None):
    s = session or requests
    r = s.get(url, headers=HEADERS, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return _decode(r.text)


def _score(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _first(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


# ------------------------------------------------------------------ ficha
def fetch_ficha_full(match_id, session=None):
    """Devuelve (match, group) de la ficha del partido."""
    data = get_json(config.FICHA_URL.format(token=config.FICHA_TOKEN, match_id=match_id), session)
    md = data.get("messageData") or {}
    m = md.get("match") or {}
    if not m.get("universallyid"):
        raise ScraperError(f"La ficha del partido {match_id} no contiene 'universallyid'")
    return m, md.get("group") or {}


def fetch_ficha(match_id, session=None):
    return fetch_ficha_full(match_id, session)[0]


def group_signature(match, group):
    if match.get("idGroup"):
        return ("g", str(match["idGroup"]))
    return (match.get("nameCategory"), match.get("nameCompetition"), group.get("nameGroup"))


def _from_ficha(m):
    ls, vs = _score(m.get("localScore")), _score(m.get("visitorScore"))
    return {"ext_id": _score(m.get("idMatch")), "uid": m.get("universallyid"), "played_at": m.get("matchDay"),
            "matchday": _score(m.get("numMatchDay")), "has_score": ls is not None and vs is not None,
            "score_listed": True}


# ------------------------------------------------------------------ listados
def find_matches(obj, matchday=None):
    """Busca recursivamente diccionarios de partido (con 'idMatch' o 'universallyid') en cualquier JSON."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "idMatch" in o or "universallyid" in o or "statsUuid" in o:
                found.append(o)
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    out = []
    for m in found:
        ls = _score(_first(m, "localScore", "local_score", "scoreLocal"))
        vs = _score(_first(m, "visitorScore", "visitor_score", "scoreVisitor", "visitScore"))
        out.append({
            "ext_id": _score(_first(m, "idMatch", "match_id", "id")),
            "uid": _first(m, "universallyid", "statsUuid", "uuid"),
            "played_at": _first(m, "matchDay", "date", "matchDate"),
            "matchday": _score(_first(m, "numMatchDay", "round", "matchday", "jornada")) or matchday,
            "has_score": ls is not None and vs is not None,
            # el listado informa de marcadores (aunque estén vacíos): permite saber si el partido está sin jugar
            "score_listed": any(k in m for k in ("localScore", "local_score", "scoreLocal")),
        })
    return out


def _scan_group(conn, session=None):
    """Estrategia C: barrido de fichas alrededor del partido semilla, conservando el mismo grupo."""
    seed_m, seed_g = fetch_ficha_full(config.SEED_MATCH_ID, session)
    sig = group_signature(seed_m, seed_g)
    negatives = set(json.loads(db.get_meta(conn, "scan_negative", "[]") or "[]"))
    known = {r["ext_id"] for r in conn.execute("SELECT ext_id FROM matches WHERE ext_id IS NOT NULL")}
    ids = [i for i in range(config.SEED_MATCH_ID - config.SCAN_RADIUS, config.SEED_MATCH_ID + config.SCAN_RADIUS + 1)
           if i != config.SEED_MATCH_ID and i not in negatives]

    def probe(i):
        try:
            m, g = fetch_ficha_full(i)
            return i, (_from_ficha(m) if group_signature(m, g) == sig else None)
        except Exception:
            return i, None

    res = [_from_ficha(seed_m)]
    new_neg = set(negatives)
    with ThreadPoolExecutor(max_workers=config.SCAN_WORKERS) as ex:
        for i, item in ex.map(probe, ids):
            if item:
                res.append(item)
            else:
                new_neg.add(i)
    if new_neg != negatives:
        db.set_meta(conn, "scan_negative", json.dumps(sorted(new_neg)))
        conn.commit()
    return res


def list_matches(conn, session=None, progress=None):
    """Devuelve (lista de partidos, nombre de la estrategia usada, notas de diagnóstico)."""
    progress = progress or (lambda m: None)
    notes = []

    if config.MATCHDAY_URL:  # A
        out, empty = [], 0
        for md in range(1, config.MAX_MATCHDAYS + 1):
            progress(f"Jornada {md}…")
            try:
                ms = find_matches(get_json(config.MATCHDAY_URL.format(group_id=config.GROUP_ID, matchday=md), session), md)
            except Exception as e:
                notes.append(f"MATCHDAY_URL jornada {md}: {e}")
                break
            empty = 0 if ms else empty + 1
            out += ms
            if empty >= 2:
                break
        if out:
            return out, "MATCHDAY_URL", notes

    if config.GROUP_MATCHES_URL:  # B
        progress("Listado del grupo…")
        try:
            url = config.GROUP_MATCHES_URL.format(token=config.FICHA_TOKEN, group_id=config.GROUP_ID)
            ms = find_matches(get_json(url, session))
            if ms:
                return ms, "listado del grupo", notes
            notes.append("El listado del grupo no devolvió partidos")
        except Exception as e:
            notes.append(f"Listado del grupo: {e}")

    progress("Buscando partidos del grupo…")  # C
    try:
        ms = _scan_group(conn, session)
        if ms:
            return ms, "barrido de fichas", notes
    except Exception as e:
        notes.append(f"Barrido de fichas: {e}")
    raise ScraperError("No se pudo obtener el listado de partidos. " + " | ".join(notes) +
                       " — Ejecuta «python -m app.cli diagnose» y revisa el README.")


def import_one(conn, ext_id=None, uid=None, matchday=None, played_at=None, session=None):
    """Descarga e importa un partido. Devuelve el id interno."""
    if not uid or not played_at or not matchday:
        ficha = fetch_ficha(ext_id, session)
        uid = uid or ficha["universallyid"]
        played_at = played_at or ficha.get("matchDay")
        matchday = matchday or _score(ficha.get("numMatchDay"))
    stats = get_json(config.STATS_URL.format(uid=uid), session)
    moves = get_json(config.MOVES_URL.format(uid=uid), session)
    return ingest_match(conn, stats, moves, uid, ext_id=ext_id, matchday=matchday, played_at=played_at)


def update_all(conn, full=False, progress=None, session=None):
    """Importa los partidos jugados que aún no están en la BD."""
    progress = progress or (lambda msg: None)
    matches, strategy, notes = list_matches(conn, session, progress)
    played = [m for m in matches if not (m["score_listed"] and not m["has_score"]) and (m["ext_id"] or m["uid"])]
    added, errors = 0, list(notes)
    for n, m in enumerate(sorted(played, key=lambda x: (x["matchday"] or 0, x["ext_id"] or 0)), 1):
        if not full and conn.execute("SELECT 1 FROM matches WHERE ext_id=? OR uid=?",
                                     (m["ext_id"], m["uid"] or "")).fetchone():
            continue
        progress(f"Descargando partido {n}/{len(played)}…")
        try:
            import_one(conn, m["ext_id"], m["uid"], m["matchday"], m["played_at"], session)
            added += 1
        except Exception as e:  # un partido sin datos no debe parar el resto
            log.warning("Partido %s: %s", m["ext_id"], e)
            errors.append(f"Partido {m['ext_id']}: {e}")
    refresh_update_meta(conn)
    return {"added": added, "errors": errors, "strategy": strategy, "found": len(matches), "played": len(played)}


def diagnose(conn):
    """Prueba cada pieza por separado y devuelve líneas de texto legibles."""
    out = []

    def step(name, fn):
        try:
            r = fn()
            out.append(f"OK    {name}: {r}")
            return r
        except Exception as e:
            out.append(f"FALLO {name}: {e}")

    m = step("ficha del partido semilla", lambda: (lambda x: f"uid={x[0]['universallyid']} jornada={x[0].get('numMatchDay')} "
                                                   f"grupo={group_signature(*x)}")(fetch_ficha_full(config.SEED_MATCH_ID)))
    if m:
        uid = fetch_ficha(config.SEED_MATCH_ID)["universallyid"]
        step("estadísticas", lambda: f"{len(get_json(config.STATS_URL.format(uid=uid)).get('teams', []))} equipos")
        step("jugada a jugada", lambda: f"{len(get_json(config.MOVES_URL.format(uid=uid)))} eventos")
    if config.MATCHDAY_URL:
        step("A) MATCHDAY_URL jornada 1", lambda: f"{len(find_matches(get_json(config.MATCHDAY_URL.format(group_id=config.GROUP_ID, matchday=1))))} partidos")
    step("B) listado del grupo", lambda: f"{len(find_matches(get_json(config.GROUP_MATCHES_URL.format(token=config.FICHA_TOKEN, group_id=config.GROUP_ID))))} partidos")
    step("C) barrido de fichas", lambda: f"{len(_scan_group(conn))} partidos del grupo")
    return out


def refresh_update_meta(conn):
    row = conn.execute("SELECT MAX(matchday) AS md FROM matches").fetchone()
    md = row["md"]
    last_date = None
    if md is not None:
        r = conn.execute("SELECT MAX(played_at) AS d FROM matches WHERE matchday=?", (md,)).fetchone()
        last_date = (r["d"] or "")[:10] or None
    db.set_meta(conn, "last_update_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    db.set_meta(conn, "last_matchday", md if md is not None else "")
    db.set_meta(conn, "last_matchday_date", last_date or "")
    conn.commit()


# ---- estado compartido para el botón «Actualizar» de la web ----
STATE = {"running": False, "message": "", "result": None}
_LOCK = threading.Lock()


def start_background_update(full=False):
    with _LOCK:
        if STATE["running"]:
            return False
        STATE.update(running=True, message="Iniciando…", result=None)

    def run():
        conn = db.connect()
        try:
            res = update_all(conn, full=full, progress=lambda m: STATE.update(message=m))
            STATE.update(result=res, message="Completado")
        except Exception as e:
            log.exception("Fallo en la actualización")
            STATE.update(result={"added": 0, "errors": [str(e)]}, message="Error")
        finally:
            conn.close()
            STATE["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return True
