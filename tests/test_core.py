import json

import pytest

from app import formula as F
from app import ingest, scraper, stats
from tests.fixtures import make_game


# ------------------------------------------------------------ fórmulas
def test_formula_ok_and_div_zero():
    f = F.compile_formula("100*a/(b+1)", {"a", "b"})
    assert f({"a": 3, "b": 2}) == 100.0
    assert F.compile_formula("a/b", {"a", "b"})({"a": 1, "b": 0}) is None


@pytest.mark.parametrize("bad", ["__import__('os')", "a.__class__", "a**2", "a if b else 1", "unknown+1",
                                 "open('x')", "[1]", "a;b", "lambda: 1", ""])
def test_formula_rejects(bad):
    with pytest.raises(F.FormulaError):
        F.validate(bad, {"a", "b"})


# ------------------------------------------------------------ ingesta
@pytest.mark.parametrize("countdown,reverse", [(True, False), (False, False), (True, True)])
def test_ingest_consistency(conn, countdown, reverse):
    st, mv, score = make_game(seed=3, countdown=countdown, reverse=reverse)
    mid = ingest.ingest_match(conn, st, mv, "uid-1", ext_id=99555, matchday=7, played_at="2026-10-24 10:00:00")
    m = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    assert (m["home_score"], m["away_score"]) == (score[1], score[2])
    assert m["clock_mode"] == ("countdown" if countdown else "countup")
    # cada equipo tiene 5 jugadores en pista los 2400 s
    for tid in (1, 2):
        secs = conn.execute("SELECT SUM(seconds) s FROM stints WHERE team_id=?", (tid,)).fetchone()["s"]
        assert secs == 2400
        psec = conn.execute("SELECT SUM(seconds) s FROM player_match WHERE team_id=?", (tid,)).fetchone()["s"]
        assert psec == 5 * 2400
        pts_for = sum(json.loads(r["stats_for"])["pts"] for r in conn.execute("SELECT * FROM stints WHERE team_id=?", (tid,)))
        assert pts_for == score[tid]
    # los quintetos siempre tienen 5 jugadores
    assert all(len(r["players"].split(",")) == 5 for r in conn.execute("SELECT players FROM stints WHERE seconds>0"))
    # el plus/minus de los jugadores de un equipo suma 5 × diferencia de puntos
    pm = conn.execute("SELECT SUM(plusminus) s FROM player_match WHERE team_id=1").fetchone()["s"]
    assert pm == 5 * (score[1] - score[2])


def test_reingest_replaces(conn):
    st, mv, _ = make_game(seed=5)
    ingest.ingest_match(conn, st, mv, "u")
    ingest.ingest_match(conn, st, mv, "u")
    assert conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM player_match").fetchone()["c"] <= 20


# ------------------------------------------------------------ estadísticas
def _load(conn, n=3):
    for i in range(n):
        h, a = ((1, "HOME"), (2, "AWAY")) if i % 2 == 0 else ((2, "AWAY"), (1, "HOME"))
        st, mv, _ = make_game(seed=10 + i, home=h, away=a)
        ingest.ingest_match(conn, st, mv, f"u{i}", matchday=i + 1, played_at=f"2026-10-{20 + i} 10:00:00")


def test_team_totals_and_advanced(conn):
    _load(conn)
    tot = stats.team_totals(conn)
    assert tot[1]["games"] == 3 and tot[1]["mins"] == 120
    assert tot[1]["pts"] == tot[2]["opp_pts"]
    t = tot[1]
    poss = t["fga"] + 0.44 * t["fta"] - t["orb"] + t["tov"]
    rows, defs = stats.league_table(conn, per_game=False)
    r = next(x for x in rows if x["team_id"] == 1)["values"]
    assert r["ortg"] == pytest.approx(100 * t["pts"] / poss)
    assert r["efg"] == pytest.approx(100 * (t["fgm"] + 0.5 * t["fg3m"]) / t["fga"])
    assert r["opp_efg"] is not None and r["opp_tov_pct"] is not None
    # por partido divide las métricas extensivas pero no los porcentajes
    pg, _ = stats.league_table(conn, per_game=True)
    r2 = next(x for x in pg if x["team_id"] == 1)["values"]
    assert r2["pts"] == pytest.approx(r["pts"] / 3) and r2["efg"] == pytest.approx(r["efg"])
    assert r["net"] == pytest.approx(-next(x for x in rows if x["team_id"] == 2)["values"]["net"], abs=15)


def test_custom_metric(conn):
    _load(conn, 2)
    stats.validate_custom("pts_por_pos", "pts/poss")
    conn.execute("INSERT INTO custom_metrics(key,label,formula,decimals) VALUES('pts_por_pos','PPP','pts/poss',2)")
    rows, defs = stats.league_table(conn, per_game=True)
    assert "pts_por_pos" in defs[-1]["key"]
    v = rows[0]["values"]["pts_por_pos"]
    assert 0.3 < v < 3
    with pytest.raises(F.FormulaError):
        stats.validate_custom("pts", "pts/poss")  # clave ya usada
    with pytest.raises(F.FormulaError):
        stats.validate_custom("x1", "pts/otra_cosa")


def test_players_and_lineups(conn):
    _load(conn)
    pl = stats.player_stats(conn, 1)
    assert pl and sum(p["min_total"] for p in pl) == pytest.approx(5 * 120)
    assert all(p["usg"] is not None for p in pl if p["min_total"] > 5)
    quint = stats.lineup_stats(conn, 1, 5)
    assert sum(q["minutes"] for q in quint) == pytest.approx(120)
    pairs = stats.lineup_stats(conn, 1, 2)
    assert sum(q["minutes"] for q in pairs) == pytest.approx(120 * 10)  # 10 parejas por quinteto
    trios = stats.lineup_stats(conn, 1, 3, min_seconds=60)
    assert all(q["minutes"] >= 1 for q in trios)
    assert len(stats.team_game_log(conn, 1)) == 3


# ------------------------------------------------------------ scraper
def test_decode_base64_and_find_matches():
    import base64
    payload = {"messageData": {"match": {"idMatch": "99555", "universallyid": "abc"}}}
    assert scraper._decode(base64.b64encode(json.dumps(payload).encode()).decode()) == payload
    found = scraper.find_matches({"x": [{"idMatch": 5, "localScore": "10", "visitorScore": "8", "numMatchDay": "2"},
                                        {"idMatch": 6, "localScore": None, "visitorScore": None}]})
    assert found[0]["has_score"] and found[0]["matchday"] == 2 and not found[1]["has_score"]


def test_update_all_with_fake_api(conn, monkeypatch):
    games = {}
    for i, mid in enumerate((101, 102)):
        games[f"uid{mid}"] = make_game(seed=20 + i)

    def fake_get_json(url, session=None):
        if "listado" in url:
            md = int(url.rsplit("/", 1)[1])
            if md == 1:
                return {"matches": [{"idMatch": 101, "universallyid": "uid101", "localScore": 80, "visitorScore": 70,
                                     "numMatchDay": 1, "matchDay": "2026-10-10 10:00:00"},
                                    {"idMatch": 102, "universallyid": "uid102", "localScore": 60, "visitorScore": 50,
                                     "numMatchDay": 1, "matchDay": "2026-10-11 10:00:00"},
                                    {"idMatch": 103, "universallyid": "uid103", "localScore": None, "visitorScore": None}]}
            return {"matches": []}
        uid = url.split("/")[-1].split("?")[0]
        if "getJsonWithMatchStats" in url:
            return games[uid][0]
        if "getJsonWithMatchMoves" in url:
            return games[uid][1]
        raise AssertionError(url)

    monkeypatch.setattr(scraper, "get_json", fake_get_json)
    monkeypatch.setattr(scraper.config, "MATCHDAY_URL", "http://x/listado/{group_id}/{matchday}")
    res = scraper.update_all(conn)
    assert res["added"] == 2 and not res["errors"]
    assert scraper.update_all(conn)["added"] == 0  # idempotente
    from app import db
    assert db.get_meta(conn, "last_matchday") == "1"
    assert db.get_meta(conn, "last_matchday_date") == "2026-10-11"


def _ficha(mid, uid, md, group="Unico", scores=(80, 70), cat="Liga Vasca Cad.Mas."):
    import base64
    body = {"result": "OK", "errorCode": 0, "messageData": {
        "match": {"idMatch": str(mid), "universallyid": uid, "matchDay": f"2026-10-{md + 10} 10:00:00",
                  "numMatchDay": str(md), "localScore": None if scores is None else str(scores[0]),
                  "visitorScore": None if scores is None else str(scores[1]), "nameCategory": cat,
                  "nameCompetition": "LVCM-Primera Fase"}, "group": {"nameGroup": group}}}
    return base64.b64encode(json.dumps(body).encode()).decode()


def _api(games, fichas, group_listing=None):
    """Simula la API: fichas por id, listado de grupo opcional y stats/moves por uid."""
    import requests

    class R:
        def __init__(self, text, status=200):
            self.text, self.status_code = text, status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

    def get(url, headers=None, timeout=None):
        if "fitxaPartit" in url:
            mid = int(url.rsplit("/", 1)[1])
            return R(fichas[mid]) if mid in fichas else R(json.dumps({"result": "OK", "errorCode": 0, "messageData": {}}))
        if "getAllGamesByGrup" in url:
            if group_listing is None:
                return R(json.dumps({"result": "ERROR", "errorCode": "x0008"}))
            return R(json.dumps(group_listing))
        uid = url.split("/")[-1].split("?")[0]
        if "MatchStats" in url:
            return R(json.dumps(games[uid][0]))
        if "MatchMoves" in url:
            return R(json.dumps(games[uid][1]))
        return R("", 404)

    return get


def test_error_body_with_http_200_is_detected():
    with pytest.raises(scraper.ScraperError, match="x0008"):
        scraper._decode('{"result":"ACCESS DENIED","errorCode":"x0008"}')


def test_strategy_group_listing(conn, monkeypatch):
    games = {"ua": make_game(seed=61), "ub": make_game(seed=62)}
    listing = {"result": "OK", "messageData": {"games": [
        {"idMatch": "201", "universallyid": "ua", "numMatchDay": "1", "localScore": "90", "visitorScore": "80", "matchDay": "2026-10-11 10:00:00"},
        {"idMatch": "202", "universallyid": "ub", "numMatchDay": "2", "localScore": "70", "visitorScore": "60", "matchDay": "2026-10-18 10:00:00"},
        {"idMatch": "203", "universallyid": "uc", "numMatchDay": "3", "localScore": None, "visitorScore": None}]}}
    monkeypatch.setattr(scraper.requests, "get", _api(games, {}, listing))
    monkeypatch.setattr(scraper.config, "MATCHDAY_URL", "")
    res = scraper.update_all(conn)
    assert res["strategy"] == "listado del grupo" and res["added"] == 2 and res["played"] == 2
    assert not res["errors"]


def test_strategy_scan_fallback_filters_by_group(conn, monkeypatch):
    games = {"ua": make_game(seed=71), "ub": make_game(seed=72)}
    fichas = {
        100: _ficha(100, "ua", 6), 101: _ficha(101, "ub", 7, scores=(66, 60)),
        102: _ficha(102, "ux", 7, group="Grupo B"),             # otro grupo: se descarta
        103: _ficha(103, "uf", 8, scores=None),                   # futuro: sin marcador, no se descarga
        104: _ficha(104, "uy", 7, cat="Otra categoría"),         # otra categoría: se descarta
    }
    monkeypatch.setattr(scraper.requests, "get", _api(games, fichas, None))
    monkeypatch.setattr(scraper.config, "MATCHDAY_URL", "")
    monkeypatch.setattr(scraper.config, "SEED_MATCH_ID", 100)
    monkeypatch.setattr(scraper.config, "SCAN_RADIUS", 6)
    res = scraper.update_all(conn)
    assert res["strategy"] == "barrido de fichas"
    assert res["found"] == 3 and res["played"] == 2 and res["added"] == 2
    from app import db
    assert db.get_meta(conn, "last_matchday") == "7"
    assert 102 in json.loads(db.get_meta(conn, "scan_negative"))
    assert scraper.update_all(conn)["added"] == 0  # idempotente


def test_no_strategy_works_gives_clear_error(conn, monkeypatch):
    monkeypatch.setattr(scraper.requests, "get", _api({}, {}, None))
    monkeypatch.setattr(scraper.config, "MATCHDAY_URL", "")
    with pytest.raises(scraper.ScraperError, match="diagnose"):
        scraper.update_all(conn)


def test_diagnose_reports_each_step(conn, monkeypatch):
    games = {"ua": make_game(seed=81)}
    monkeypatch.setattr(scraper.requests, "get", _api(games, {99555: _ficha(99555, "ua", 7)}, None))
    out = scraper.diagnose(conn)
    assert out[0].startswith("OK    ficha") and any(l.startswith("FALLO B)") for l in out) and any("C) barrido" in l and l.startswith("OK") for l in out)
