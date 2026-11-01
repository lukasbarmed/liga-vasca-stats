"""Convierte los JSON de un partido (estadísticas + jugada a jugada) en filas de la BD.

Entradas esperadas (formato observado en msstats.optimalwayconsulting.com):
  * stats: dict con 'teams' -> 'players' -> 'data' (totales por jugador), 'localId', 'visitId'...
  * moves: lista de eventos {idTeam, actorId, actorName, idMove, move, min, sec, period, score, ...}

Los quintetos en pista se reconstruyen con el quinteto inicial ('starting' en stats) y los
eventos 112 (entra al campo) / 115 (sale del campo).
"""
import json
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# Contadores que se acumulan por tramo (stint) para los análisis de combinaciones
STINT_KEYS = ["pts", "fta", "ftm", "fg2a", "fg2m", "fg3a", "fg3m",
              "orb", "drb", "ast", "stl", "blk", "tov", "pf"]

# idMove -> {contador: incremento}
MOVE_EFFECTS = {
    92: {"ftm": 1, "fta": 1, "pts": 1},
    93: {"fg2m": 1, "fg2a": 1, "pts": 2},
    94: {"fg3m": 1, "fg3a": 1, "pts": 3},
    96: {"fta": 1},
    97: {"fg2a": 1},
    98: {"fg3a": 1},
    101: {"orb": 1},
    102: {"blk": 1},
    103: {"stl": 1},
    104: {"drb": 1},
    106: {"tov": 1},
    107: {"ast": 1},
    159: {"pf": 1}, 160: {"pf": 1}, 161: {"pf": 1},
}
MOVE_IN, MOVE_OUT, MOVE_END_PERIOD = 112, 115, 116

# columna BD -> clave en player['data']
PLAYER_FIELDS = {
    "pts": "score", "fta": "shotsOfOneAttempted", "ftm": "shotsOfOneSuccessful",
    "fg2a": "shotsOfTwoAttempted", "fg2m": "shotsOfTwoSuccessful",
    "fg3a": "shotsOfThreeAttempted", "fg3m": "shotsOfThreeSuccessful",
    "orb": "offensiveRebound", "drb": "defensiveRebound", "ast": "assists",
    "stl": "steals", "blk": "block", "blk_rec": "blockReceived",
    "tov": "lost", "pf": "faults", "pf_rec": "faultReceived", "val": "valoration",
}


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_time(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%b %d, %Y, %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _moves_list(moves):
    if isinstance(moves, dict):
        for k in ("moves", "data", "messageData"):
            if isinstance(moves.get(k), list):
                return moves[k]
        return []
    return moves or []


def _period_durations(stats, max_period):
    lst = stats.get("periodDurationList") or []
    base = _int(stats.get("periodDuration"), 10) or 10
    n = max(_int(stats.get("period"), 4), max_period, len(lst))
    durs = [(_int(lst[i]) if i < len(lst) else (base if i < 4 else 5)) for i in range(n)]
    return durs


def _detect_countdown(events):
    first = [e for e in events if _int(e.get("period"), 1) == 1 and _int(e.get("idMove")) != MOVE_END_PERIOD]
    if len(first) < 2:
        return True
    a = _int(first[0].get("min")) * 60 + _int(first[0].get("sec"))
    b = _int(first[-1].get("min")) * 60 + _int(first[-1].get("sec"))
    if a == b:
        return True
    return a > b


def _blank():
    return {k: 0 for k in STINT_KEYS}


def build_stints(stats, events, team_ids, rosters, starters, durs):
    """Devuelve (stints, player_seconds, player_pm, ordered_events)."""
    # 1) orden del array: si empieza en un periodo posterior al que acaba, viene del revés
    if len(events) > 1 and _int(events[0].get("period"), 1) > _int(events[-1].get("period"), 1):
        events = events[::-1]
    # 2) tipo de reloj (descendente o ascendente) con el array ya en orden cronológico
    countdown = _detect_countdown(events)
    starts, acc = [], 0
    for d in durs:
        starts.append(acc)
        acc += d * 60
    total = acc

    def elapsed(e):
        p = max(1, _int(e.get("period"), 1))
        if p > len(durs):
            return total
        clock = _int(e.get("min")) * 60 + _int(e.get("sec"))
        within = durs[p - 1] * 60 - clock if countdown else clock
        within = min(max(within, 0), durs[p - 1] * 60)
        return starts[p - 1] + within

    evs = [dict(e, _t=elapsed(e)) for e in events]
    evs.sort(key=lambda e: e["_t"])  # estable: respeta el orden dentro del mismo segundo

    lineup = {t: set(starters[t]) for t in team_ids}
    cur = {t: {"t0": 0, "for": _blank(), "against": _blank()} for t in team_ids}
    stints, pseconds, ppm = [], {}, {}

    def close(team, t_end):
        s = cur[team]
        dur = max(0, t_end - s["t0"])
        players = sorted(lineup[team])
        has_stats = any(s["for"].values()) or any(s["against"].values())
        if players and (dur > 0 or has_stats):
            stints.append({"team_id": team, "players": players, "seconds": dur,
                           "for": s["for"], "against": s["against"]})
            for pid in players:
                pseconds[pid] = pseconds.get(pid, 0) + dur
                ppm[pid] = ppm.get(pid, 0) + s["for"]["pts"] - s["against"]["pts"]
        cur[team] = {"t0": t_end, "for": _blank(), "against": _blank()}

    for e in evs:
        mid, team, pid, t = _int(e.get("idMove")), _int(e.get("idTeam")), e.get("actorId"), e["_t"]
        if team not in cur:
            continue
        if mid in (MOVE_IN, MOVE_OUT):
            if pid is None:
                continue
            close(team, t)
            if mid == MOVE_IN:
                lineup[team].add(pid)
            else:
                lineup[team].discard(pid)
            continue
        eff = MOVE_EFFECTS.get(mid)
        if not eff:
            continue
        for tm in team_ids:
            side = "for" if tm == team else "against"
            for k, v in eff.items():
                cur[tm][side][k] += v
    for t in team_ids:
        close(t, max(total, evs[-1]["_t"] if evs else 0))
    return stints, pseconds, ppm, evs, ("countdown" if countdown else "countup")


def _infer_starters(team, evs, roster_ids):
    seen_in, starters = set(), set()
    for e in evs:
        if _int(e.get("idTeam")) != team or e.get("actorId") is None:
            continue
        pid, mid = e["actorId"], _int(e.get("idMove"))
        if mid == MOVE_IN:
            seen_in.add(pid)
        elif pid not in seen_in:
            starters.add(pid)
            seen_in.add(pid)
    return starters


def ingest_match(conn, stats, moves, uid, ext_id=None, matchday=None, played_at=None):
    """Guarda (o reemplaza) un partido. Devuelve el id interno del partido."""
    teams = stats.get("teams") or []
    if len(teams) != 2:
        raise ValueError("El JSON de estadísticas debe contener exactamente 2 equipos")
    home_id, away_id = _int(stats.get("localId")), _int(stats.get("visitId"))
    by_id = {_int(t.get("teamIdIntern")): t for t in teams}
    if home_id not in by_id or away_id not in by_id:  # fallback: orden del array
        home_id, away_id = _int(teams[0].get("teamIdIntern")), _int(teams[1].get("teamIdIntern"))
        by_id = {home_id: teams[0], away_id: teams[1]}
    team_ids = [home_id, away_id]

    events = _moves_list(moves)
    max_p = max([_int(e.get("period"), 1) for e in events] or [1])
    durs = _period_durations(stats, max_p)
    minutes = sum(durs)

    # --- jugadores y totales ---
    rosters, starters, rows, names = {}, {}, {}, {}
    for tid in team_ids:
        rosters[tid] = []
        starters[tid] = {p["actorId"] for p in by_id[tid].get("players", []) if p.get("starting")}
        for p in by_id[tid].get("players", []):
            d = p.get("data") or {}
            row = {c: _int(d.get(src)) for c, src in PLAYER_FIELDS.items()}
            row.update(team_id=tid, player_id=p["actorId"], name=(p.get("name") or "").strip(),
                       dorsal=str(p.get("dorsal") or ""), starting=1 if p.get("starting") else 0,
                       timeplayed=_int(p.get("timePlayed")))
            rows[p["actorId"]] = row
            rosters[tid].append(p["actorId"])
            # comprobación de integridad: puntos = TL + 2*T2 + 3*T3
            calc = row["ftm"] + 2 * row["fg2m"] + 3 * row["fg3m"]
            if calc != row["pts"]:
                log.warning("Partido %s: %s puntos=%s pero tiros suman %s", uid, row["name"], row["pts"], calc)
    for e in events:
        if e.get("actorId") is not None and e.get("actorName"):
            names[e["actorId"]] = e["actorName"]

    for tid in team_ids:
        if not starters[tid]:
            starters[tid] = _infer_starters(tid, events, rosters[tid])

    stints, pseconds, ppm, ordered, clock_mode = ([], {}, {}, [], None)
    if events:
        stints, pseconds, ppm, ordered, clock_mode = build_stints(
            stats, events, team_ids, rosters, starters, durs)

    score = {tid: sum(rows[p]["pts"] for p in rosters[tid]) for tid in team_ids}

    # --- escritura ---
    old = conn.execute("SELECT id FROM matches WHERE uid=?", (uid,)).fetchone()
    if old:
        conn.execute("DELETE FROM matches WHERE id=?", (old["id"],))
    for tid in team_ids:
        t = by_id[tid]
        conn.execute(
            "INSERT INTO teams(id,name,short_name) VALUES(?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, short_name=excluded.short_name",
            (tid, (t.get("name") or str(tid)).strip(), t.get("shortName")))
    cur = conn.execute(
        "INSERT INTO matches(uid,ext_id,matchday,played_at,home_id,away_id,home_score,away_score,minutes,clock_mode) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid, ext_id, matchday, played_at or _parse_time(stats.get("time")),
         home_id, away_id, score[home_id], score[away_id], minutes, clock_mode))
    mid = cur.lastrowid

    for pid, row in rows.items():
        secs = pseconds.get(pid, 0) if events else row["timeplayed"] * 60
        empty = secs == 0 and not any(row[c] for c in PLAYER_FIELDS) and not row["starting"]
        if empty:
            continue
        cols = ["match_id", "team_id", "player_id", "name", "dorsal", "starting", "seconds", "plusminus"] + list(PLAYER_FIELDS)
        vals = [mid, row["team_id"], pid, row["name"], row["dorsal"], row["starting"], secs, ppm.get(pid, 0)] + \
               [row[c] for c in PLAYER_FIELDS]
        conn.execute(f"INSERT INTO player_match({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)

    for seq, e in enumerate(ordered):
        pid = e.get("actorId")
        conn.execute(
            "INSERT INTO moves(match_id,seq,team_id,player_id,player_name,move_id,move,period,clock_min,clock_sec,elapsed,score) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, seq, _int(e.get("idTeam")) or None, pid, e.get("actorName") or None,
             _int(e.get("idMove")), e.get("move"), _int(e.get("period"), 1),
             _int(e.get("min")), _int(e.get("sec")), e["_t"], e.get("score")))
    for s in stints:
        conn.execute(
            "INSERT INTO stints(match_id,team_id,players,seconds,stats_for,stats_against) VALUES(?,?,?,?,?,?)",
            (mid, s["team_id"], ",".join(str(p) for p in s["players"]), s["seconds"],
             json.dumps(s["for"]), json.dumps(s["against"])))
    conn.commit()
    return mid
