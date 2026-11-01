"""Cálculo de estadísticas básicas, avanzadas, de jugadores y de combinaciones en pista.

Las métricas se definen como fórmulas sobre *totales acumulados* del equipo (prefijo opp_ = rival).
Las métricas personalizadas de los gestores usan exactamente el mismo mecanismo.
"""
import itertools
import json

from . import formula as F

BASE = ["pts", "fta", "ftm", "fg2a", "fg2m", "fg3a", "fg3m", "orb", "drb",
        "ast", "stl", "blk", "blk_rec", "tov", "pf", "pf_rec"]

# ---------------------------------------------------------------- definiciones de métricas
# kind: 'count' (extensiva: en modo "por partido" se divide entre partidos) | 'rate' (no se divide)
# hb: higher_better (True/False/None)
def _m(key, label, formula, kind="rate", dec=1, hb=None, group="basic", desc=""):
    return dict(key=key, label=label, formula=formula, kind=kind, dec=dec, hb=hb, group=group, desc=desc)


BASIC_METRICS = [
    _m("pts", "Puntos", "pts", "count", 1, True),
    _m("opp_pts", "Puntos recibidos", "opp_pts", "count", 1, False),
    _m("fgm", "Tiros de campo anotados", "fgm", "count", 1, True),
    _m("fga", "Tiros de campo intentados", "fga", "count", 1, None),
    _m("fg_pct", "% Tiro de campo", "100*fgm/fga", "rate", 1, True),
    _m("fg2m", "T2 anotados", "fg2m", "count", 1, True),
    _m("fg2a", "T2 intentados", "fg2a", "count", 1, None),
    _m("fg2_pct", "% T2", "100*fg2m/fg2a", "rate", 1, True),
    _m("fg3m", "T3 anotados", "fg3m", "count", 1, True),
    _m("fg3a", "T3 intentados", "fg3a", "count", 1, None),
    _m("fg3_pct", "% T3", "100*fg3m/fg3a", "rate", 1, True),
    _m("ftm", "TL anotados", "ftm", "count", 1, True),
    _m("fta", "TL intentados", "fta", "count", 1, None),
    _m("ft_pct", "% TL", "100*ftm/fta", "rate", 1, True),
    _m("orb", "Rebotes ofensivos", "orb", "count", 1, True),
    _m("drb", "Rebotes defensivos", "drb", "count", 1, True),
    _m("reb", "Rebotes totales", "reb", "count", 1, True),
    _m("ast", "Asistencias", "ast", "count", 1, True),
    _m("stl", "Robos", "stl", "count", 1, True),
    _m("blk", "Tapones", "blk", "count", 1, True),
    _m("blk_rec", "Tapones recibidos", "blk_rec", "count", 1, False),
    _m("tov", "Pérdidas", "tov", "count", 1, False),
    _m("pf", "Faltas cometidas", "pf", "count", 1, False),
    _m("pf_rec", "Faltas recibidas", "pf_rec", "count", 1, True),
]

ADVANCED_METRICS = [
    _m("poss", "Posesiones por partido", "(poss+opp_poss)/2/games", "rate", 1, None, "advanced",
       "Posesiones estimadas (propias y rivales promediadas) por partido"),
    _m("pace", "Ritmo (pos./40')", "40*((poss+opp_poss)/2)/mins", "rate", 1, None, "advanced",
       "Posesiones por 40 minutos"),
    _m("ortg", "Rating ofensivo", "100*pts/poss", "rate", 1, True, "advanced", "Puntos por 100 posesiones"),
    _m("drtg", "Rating defensivo", "100*opp_pts/opp_poss", "rate", 1, False, "advanced",
       "Puntos recibidos por 100 posesiones"),
    _m("net", "Rating neto", "100*pts/poss-100*opp_pts/opp_poss", "rate", 1, True, "advanced"),
    _m("efg", "% Tiro efectivo (eFG%)", "100*(fgm+0.5*fg3m)/fga", "rate", 1, True, "advanced",
       "(TC anotados + 0,5·T3 anotados) / TC intentados"),
    _m("opp_efg", "% Tiro efectivo permitido", "100*(opp_fgm+0.5*opp_fg3m)/opp_fga", "rate", 1, False, "advanced"),
    _m("ts", "% Tiro real (TS%)", "100*pts/(2*(fga+0.44*fta))", "rate", 1, True, "advanced"),
    _m("opp_ts", "% Tiro real permitido", "100*opp_pts/(2*(opp_fga+0.44*opp_fta))", "rate", 1, False, "advanced"),
    _m("tov_pct", "% Pérdidas", "100*tov/(fga+0.44*fta+tov)", "rate", 1, False, "advanced",
       "Pérdidas por cada 100 jugadas"),
    _m("opp_tov_pct", "% Pérdidas forzadas", "100*opp_tov/(opp_fga+0.44*opp_fta+opp_tov)", "rate", 1, True, "advanced",
       "Pérdidas del rival por cada 100 jugadas rivales"),
    _m("orb_pct", "% Rebote ofensivo", "100*orb/(orb+opp_drb)", "rate", 1, True, "advanced"),
    _m("drb_pct", "% Rebote defensivo", "100*drb/(drb+opp_orb)", "rate", 1, True, "advanced"),
    _m("reb_pct", "% Rebote total", "100*reb/(reb+opp_reb)", "rate", 1, True, "advanced"),
    _m("fg3_rate", "Uso del T3", "100*fg3a/fga", "rate", 1, None, "advanced", "T3 intentados / TC intentados"),
    _m("opp_fg3_rate", "Uso del T3 permitido", "100*opp_fg3a/opp_fga", "rate", 1, None, "advanced"),
    _m("ftr", "Ratio de TL (TL/TC)", "100*fta/fga", "rate", 1, True, "advanced", "TL intentados / TC intentados"),
    _m("opp_ftr", "Ratio de TL permitido", "100*opp_fta/opp_fga", "rate", 1, False, "advanced"),
    _m("ast_ratio", "% Canastas asistidas", "100*ast/fgm", "rate", 1, True, "advanced"),
    _m("stl_pct", "% Robos", "100*stl/opp_poss", "rate", 1, True, "advanced", "Robos por cada 100 posesiones rivales"),
    _m("blk_pct", "% Tapones", "100*blk/opp_fg2a", "rate", 1, True, "advanced", "Tapones por T2 rival intentado"),
    _m("pf_100", "Faltas por 100 pos.", "100*pf/opp_poss", "rate", 1, False, "advanced"),
]

BUILTIN = BASIC_METRICS + ADVANCED_METRICS


def context_names():
    names = {"games", "mins", "poss", "opp_poss"}
    for k in BASE + ["fgm", "fga", "reb"]:
        names.add(k)
        names.add("opp_" + k)
    return names


_CTX_NAMES = context_names()
_COMPILED = {m["key"]: F.compile_formula(m["formula"], _CTX_NAMES) for m in BUILTIN}


def custom_metric_defs(conn):
    rows = conn.execute("SELECT * FROM custom_metrics ORDER BY id").fetchall()
    return [dict(key=r["key"], label=r["label"], formula=r["formula"], kind="rate",
                 dec=r["decimals"], hb=None if r["higher_better"] is None else bool(r["higher_better"]),
                 group="custom", desc="Métrica personalizada", id=r["id"]) for r in rows]


def validate_custom(key, formula):
    if not key.isidentifier() or key in _CTX_NAMES or key in {m["key"] for m in BUILTIN}:
        raise F.FormulaError("Clave no válida o ya en uso (usa letras, números y _; sin espacios)")
    F.validate(formula, _CTX_NAMES)


# ---------------------------------------------------------------- totales de equipo
def _derive(t, prefix=""):
    p = prefix
    t[p + "fgm"] = t[p + "fg2m"] + t[p + "fg3m"]
    t[p + "fga"] = t[p + "fg2a"] + t[p + "fg3a"]
    t[p + "reb"] = t[p + "orb"] + t[p + "drb"]
    t[p + "poss"] = t[p + "fga"] + 0.44 * t[p + "fta"] - t[p + "orb"] + t[p + "tov"]


def _sum_cols():
    return ",".join(f"SUM({c}) AS {c}" for c in BASE)


def match_team_rows(conn, team_id=None):
    """Totales por (partido, equipo) con su rival: devuelve lista de dicts con claves base y opp_*."""
    q = f"""SELECT m.id AS match_id, m.matchday, m.played_at, m.minutes, m.home_id, m.away_id,
                    m.home_score, m.away_score, pm.team_id, {_sum_cols()}
            FROM player_match pm JOIN matches m ON m.id = pm.match_id
            GROUP BY pm.match_id, pm.team_id"""
    per = {}
    for r in conn.execute(q):
        per.setdefault(r["match_id"], {})[r["team_id"]] = dict(r)
    out = []
    for mid, sides in per.items():
        for tid, r in sides.items():
            if team_id is not None and tid != team_id:
                continue
            opp_id = r["away_id"] if tid == r["home_id"] else r["home_id"]
            o = sides.get(opp_id)
            if not o:
                continue
            row = {"match_id": mid, "team_id": tid, "opp_id": opp_id, "matchday": r["matchday"],
                   "played_at": r["played_at"], "mins": r["minutes"], "home": tid == r["home_id"]}
            for c in BASE:
                row[c] = r[c] or 0
                row["opp_" + c] = o[c] or 0
            out.append(row)
    return out


def _aggregate(rows):
    t = {c: 0 for c in BASE}
    t.update({"opp_" + c: 0 for c in BASE})
    t["games"], t["mins"] = 0, 0
    for r in rows:
        for c in BASE:
            t[c] += r[c]
            t["opp_" + c] += r["opp_" + c]
        t["games"] += 1
        t["mins"] += r["mins"]
    _derive(t)
    _derive(t, "opp_")
    return t


def team_totals(conn):
    by_team = {}
    for r in match_team_rows(conn):
        by_team.setdefault(r["team_id"], []).append(r)
    return {tid: _aggregate(rows) for tid, rows in by_team.items()}


def compute(ctx, defs):
    """Evalúa una lista de definiciones sobre un contexto de totales. Devuelve {key: valor|None}."""
    out = {}
    for m in defs:
        fn = _COMPILED.get(m["key"]) or F.compile_formula(m["formula"], _CTX_NAMES)
        v = fn(ctx) if ctx.get("games") else None
        out[m["key"]] = v
    return out


def display_value(m, ctx, value, per_game):
    """Aplica el modo por partido a las métricas extensivas."""
    if value is None:
        return None
    if per_game and m["kind"] == "count" and ctx.get("games"):
        return value / ctx["games"]
    return value


def league_table(conn, per_game=True):
    """Tabla de la liga: lista de filas {team_id, name, games, values{key:valor}} + definiciones."""
    defs = BUILTIN + custom_metric_defs(conn)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM teams")}
    rows = []
    for tid, ctx in team_totals(conn).items():
        vals = compute(ctx, defs)
        shown = {m["key"]: display_value(m, ctx, vals[m["key"]], per_game) for m in defs}
        rows.append({"team_id": tid, "name": names.get(tid, str(tid)), "games": ctx["games"], "values": shown})
    rows.sort(key=lambda r: r["name"])
    return rows, defs


def add_ranks(rows, defs):
    for m in defs:
        if m["hb"] is None:
            continue
        vals = sorted([r["values"][m["key"]] for r in rows if r["values"][m["key"]] is not None],
                      reverse=bool(m["hb"]))
        for r in rows:
            v = r["values"][m["key"]]
            r.setdefault("ranks", {})[m["key"]] = (vals.index(v) + 1) if v is not None else None
    return rows


def league_averages(rows, defs):
    avg = {}
    for m in defs:
        vs = [r["values"][m["key"]] for r in rows if r["values"][m["key"]] is not None]
        avg[m["key"]] = sum(vs) / len(vs) if vs else None
    return avg


def team_game_log(conn, team_id):
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM teams")}
    out = []
    for r in sorted(match_team_rows(conn, team_id), key=lambda x: (x["played_at"] or "", x["match_id"])):
        ctx = dict(r, games=1)
        _derive(ctx); _derive(ctx, "opp_")
        out.append({
            "match_id": r["match_id"], "matchday": r["matchday"], "played_at": r["played_at"],
            "opp": names.get(r["opp_id"], "?"), "home": r["home"], "pts": r["pts"], "opp_pts": r["opp_pts"],
            "ortg": F.compile_formula("100*pts/poss", _CTX_NAMES)(ctx),
            "drtg": F.compile_formula("100*opp_pts/opp_poss", _CTX_NAMES)(ctx),
            "efg": F.compile_formula("100*(fgm+0.5*fg3m)/fga", _CTX_NAMES)(ctx),
            "poss": (ctx["poss"] + ctx["opp_poss"]) / 2,
        })
    return out


# ---------------------------------------------------------------- jugadores
def player_stats(conn, team_id):
    cols = ",".join(f"SUM({c}) AS {c}" for c in BASE + ["val", "plusminus", "seconds", "starting"])
    rows = conn.execute(
        f"""SELECT player_id, MAX(name) AS name, MAX(dorsal) AS dorsal, COUNT(*) AS games, {cols}
            FROM player_match WHERE team_id=? GROUP BY player_id""", (team_id,)).fetchall()
    team = team_totals(conn).get(team_id)
    out = []
    for r in rows:
        d = dict(r)
        g, sec = d["games"], d["seconds"] or 0
        fgm, fga = d["fg2m"] + d["fg3m"], d["fg2a"] + d["fg3a"]
        reb = d["orb"] + d["drb"]
        poss_used = fga + 0.44 * d["fta"] + d["tov"]

        def div(a, b, k=1.0):
            return (a / b * k) if b else None

        usg = None
        if team and sec:
            team_poss_used = team["fga"] + 0.44 * team["fta"] + team["tov"]
            usg = div(poss_used * (team["mins"] * 60 / 5), sec * team_poss_used, 100)
        out.append({
            "player_id": d["player_id"], "name": d["name"], "dorsal": d["dorsal"], "games": g,
            "starts": d["starting"], "min": sec / 60 / g if g else 0, "min_total": sec / 60,
            "pts": d["pts"] / g, "reb": reb / g, "orb": d["orb"] / g, "drb": d["drb"] / g,
            "ast": d["ast"] / g, "stl": d["stl"] / g, "blk": d["blk"] / g, "tov": d["tov"] / g,
            "pf": d["pf"] / g, "pf_rec": d["pf_rec"] / g, "val": d["val"] / g,
            "pm": d["plusminus"] / g,
            "fg_pct": div(fgm, fga, 100), "fg2_pct": div(d["fg2m"], d["fg2a"], 100),
            "fg3_pct": div(d["fg3m"], d["fg3a"], 100), "ft_pct": div(d["ftm"], d["fta"], 100),
            "fg3a": d["fg3a"] / g, "fta": d["fta"] / g,
            "efg": div(fgm + 0.5 * d["fg3m"], fga, 100),
            "ts": div(d["pts"], 2 * (fga + 0.44 * d["fta"]), 100),
            "tov_pct": div(d["tov"], poss_used, 100),
            "ast_tov": div(d["ast"], d["tov"]),
            "usg": usg,
            "pts36": div(d["pts"], sec, 36 * 60), "reb36": div(reb, sec, 36 * 60),
            "ast36": div(d["ast"], sec, 36 * 60),
        })
    out.sort(key=lambda r: -r["min_total"])
    return out


# ---------------------------------------------------------------- combinaciones en pista
def _poss(s):
    return s["fg2a"] + s["fg3a"] + 0.44 * s["fta"] - s["orb"] + s["tov"]


def lineup_stats(conn, team_id, size, min_seconds=0):
    """Estadísticas de parejas (2), tríos (3), cuartetos (4) o quintetos (5) en pista."""
    names = {r["player_id"]: r["name"] for r in conn.execute(
        "SELECT player_id, MAX(name) AS name FROM player_match WHERE team_id=? GROUP BY player_id", (team_id,))}
    acc = {}
    for st in conn.execute("SELECT match_id, players, seconds, stats_for, stats_against FROM stints WHERE team_id=?",
                           (team_id,)):
        pl = [int(x) for x in st["players"].split(",") if x]
        if len(pl) < size or (size == 5 and len(pl) != 5):
            continue
        sf, sa = json.loads(st["stats_for"]), json.loads(st["stats_against"])
        for combo in itertools.combinations(pl, size):
            a = acc.setdefault(combo, {"seconds": 0, "games": set(),
                                       "f": {k: 0 for k in sf}, "a": {k: 0 for k in sa}})
            a["seconds"] += st["seconds"]
            a["games"].add(st["match_id"])
            for k, v in sf.items():
                a["f"][k] += v
            for k, v in sa.items():
                a["a"][k] += v
    out = []
    for combo, a in acc.items():
        if a["seconds"] < min_seconds or a["seconds"] == 0:
            continue
        f, o = a["f"], a["a"]
        pf_, po_ = _poss(f), _poss(o)
        fga, ofga = f["fg2a"] + f["fg3a"], o["fg2a"] + o["fg3a"]

        def pct(n, d):
            return 100 * n / d if d else None

        out.append({
            "players": [names.get(p, str(p)) for p in combo], "minutes": a["seconds"] / 60,
            "games": len(a["games"]), "pts": f["pts"], "opp_pts": o["pts"],
            "net": f["pts"] - o["pts"], "net40": (f["pts"] - o["pts"]) / a["seconds"] * 2400,
            "poss": (pf_ + po_) / 2,
            "ortg": pct(f["pts"], pf_), "drtg": pct(o["pts"], po_),
            "net_rtg": (pct(f["pts"], pf_) - pct(o["pts"], po_)) if pf_ and po_ else None,
            "efg": pct(f["fg2m"] + f["fg3m"] + 0.5 * f["fg3m"], fga),
            "opp_efg": pct(o["fg2m"] + o["fg3m"] + 0.5 * o["fg3m"], ofga),
            "tov_pct": pct(f["tov"], fga + 0.44 * f["fta"] + f["tov"]),
            "opp_tov_pct": pct(o["tov"], ofga + 0.44 * o["fta"] + o["tov"]),
            "orb_pct": pct(f["orb"], f["orb"] + o["drb"]), "drb_pct": pct(f["drb"], f["drb"] + o["orb"]),
            "fg3_rate": pct(f["fg3a"], fga), "ftr": pct(f["fta"], fga),
        })
    out.sort(key=lambda r: -r["minutes"])
    return out
