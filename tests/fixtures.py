"""Generador de partidos sintéticos con el mismo formato que los JSON de msstats.optimalwayconsulting.com."""
import random

DATA_KEYS = ["score", "valoration", "shotsOfOneAttempted", "shotsOfTwoAttempted", "shotsOfThreeAttempted",
             "shotsOfOneSuccessful", "shotsOfTwoSuccessful", "shotsOfThreeSuccessful", "faults", "rebounds",
             "assists", "lost", "block", "steals", "blockReceived", "faultReceived", "offensiveRebound",
             "defensiveRebound"]


def make_game(seed=1, home=(1, "HOME"), away=(2, "AWAY"), countdown=True, reverse=False):
    rnd = random.Random(seed)
    teams = {}
    for tid, name in (home, away):
        players = []
        for i in range(10):
            players.append({"actorId": tid * 100 + i, "name": f"{name} JUGADOR{i}", "dorsal": str(i + 4),
                            "starting": i < 5, "playerInternTeam": tid, "timePlayed": 0,
                            "data": {k: 0 for k in DATA_KEYS}})
        teams[tid] = {"teamIdIntern": tid, "name": name, "shortName": name[:3], "players": players}
    on = {tid: [p["actorId"] for p in teams[tid]["players"][:5]] for tid in teams}
    bench = {tid: [p["actorId"] for p in teams[tid]["players"][5:]] for tid in teams}
    by_pid = {p["actorId"]: p for t in teams.values() for p in t["players"]}
    nm = {pid: p["name"] for pid, p in by_pid.items()}
    moves = []
    score = {home[0]: 0, away[0]: 0}

    def clock(t):
        sec_in = t % 600
        if countdown:
            c = 600 - sec_in
            return c // 60, c % 60
        return sec_in // 60, sec_in % 60

    def add(t, tid, pid, mid, text, **extra):
        mn, sc = clock(t)
        ev = {"idTeam": tid, "actorName": nm.get(pid, ""), "actorId": pid, "idMove": mid, "move": text,
              "min": mn, "sec": sc, "period": t // 600 + 1, "score": f"{score[home[0]]}-{score[away[0]]}",
              "teamAction": pid is None}
        ev.update(extra)
        moves.append(ev)

    def bump(pid, **kv):
        d = by_pid[pid]["data"]
        for k, v in kv.items():
            d[k] += v

    t, poss = 0, home[0]
    next_sub = {home[0]: 100, away[0]: 130}
    while t < 2399:
        t += rnd.randint(6, 22)
        if t >= 2400:
            break
        for tid in (home[0], away[0]):
            if t >= next_sub[tid]:
                next_sub[tid] += rnd.randint(90, 200)
                out, inn = rnd.choice(on[tid]), rnd.choice(bench[tid])
                add(t, tid, out, 115, "Sale del campo")
                add(t, tid, inn, 112, "Entra al campo")
                on[tid].remove(out); bench[tid].remove(inn); on[tid].append(inn); bench[tid].append(out)
        opp = away[0] if poss == home[0] else home[0]
        shooter = rnd.choice(on[poss])
        r = rnd.random()
        if r < 0.12:
            add(t, poss, shooter, 106, "Pérdida"); bump(shooter, lost=1)
            if rnd.random() < 0.5:
                s = rnd.choice(on[opp]); add(t, opp, s, 103, "Recuperación"); bump(s, steals=1)
        elif r < 0.25:
            fouler = rnd.choice(on[opp])
            add(t, opp, fouler, 161, "Personal con 2 tiros libres"); bump(fouler, faults=1)
            add(t, poss, shooter, 110, "Falta recibida"); bump(shooter, faultReceived=1)
            for _ in range(2):
                if rnd.random() < 0.72:
                    score[poss] += 1; add(t, poss, shooter, 92, "Canasta de 1")
                    bump(shooter, score=1, shotsOfOneAttempted=1, shotsOfOneSuccessful=1)
                else:
                    add(t, poss, shooter, 96, "Intento fallado de 1"); bump(shooter, shotsOfOneAttempted=1)
        else:
            three = rnd.random() < 0.33
            pts = 3 if three else 2
            att, suc = ("shotsOfThreeAttempted", "shotsOfThreeSuccessful") if three else ("shotsOfTwoAttempted", "shotsOfTwoSuccessful")
            if rnd.random() < (0.34 if three else 0.5):
                score[poss] += pts
                add(t, poss, shooter, 94 if three else 93, f"Canasta de {pts}")
                bump(shooter, score=pts, **{att: 1, suc: 1})
                if rnd.random() < 0.5:
                    a = rnd.choice([p for p in on[poss] if p != shooter]); add(t, poss, a, 107, "Asistencia"); bump(a, assists=1)
            else:
                add(t, poss, shooter, 98 if three else 97, f"Intento fallado de {pts}"); bump(shooter, **{att: 1})
                if rnd.random() < 0.28:
                    b = rnd.choice(on[opp]); add(t, opp, b, 102, "Tapón"); bump(b, block=1)
                    bump(shooter, blockReceived=1)
                if rnd.random() < 0.3:
                    p2 = rnd.choice(on[poss]); add(t, poss, p2, 101, "Rebote ofensivo"); bump(p2, offensiveRebound=1, rebounds=1)
                    continue
                p2 = rnd.choice(on[opp]); add(t, opp, p2, 104, "Rebote defensivo"); bump(p2, defensiveRebound=1, rebounds=1)
        poss = opp
    for p in range(1, 5):
        mn, sc = clock((p - 1) * 600 + 599)
        moves.append({"idTeam": 0, "actorName": "", "idMove": 116, "move": "Fin de período", "min": 0 if countdown else 10,
                      "sec": 0, "period": p, "score": f"{score[home[0]]}-{score[away[0]]}", "teamAction": True})
    # los fines de período se colocan al final de su periodo (orden cronológico)
    ordered = []
    ends = [m for m in moves if m["idMove"] == 116]
    body = [m for m in moves if m["idMove"] != 116]
    for p in range(1, 5):
        ordered += [m for m in body if m["period"] == p] + [e for e in ends if e["period"] == p]
    if reverse:
        ordered.reverse()
    for t_ in teams.values():
        for pl in t_["players"]:
            pl["data"]["valoration"] = pl["data"]["score"]
    stats = {"idMatchIntern": 1, "time": "Oct 24, 2026, 12:00:00 PM", "localId": home[0], "visitId": away[0],
             "period": 4, "periodDuration": 10, "periodDurationList": [10, 10, 10, 10],
             "moves": [], "score": [], "teams": [teams[home[0]], teams[away[0]]]}
    return stats, ordered, dict(score)
