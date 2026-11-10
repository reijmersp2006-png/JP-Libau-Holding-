"""De Risicodirecteur: kijkt over de afdelingen heen naar het wildste deel van de holding.

Crypto en memecoins samen (de "risicovleugel") bewegen het wildst en vaak tegelijk. De regel
is simpel: hoe wilder die vleugel de laatste 60 dagen bewoog, hoe minder ervan in de markt
zit. Het doel is 40% beweeglijkheid per jaar. Beweegt de vleugel 80%, dan zit maar de helft in
de markt en staat de rest als geld klaar. Nooit meer dan 100%: de directeur leent nooit bij,
en nooit minder dan een kwart.

Hij past de stand alleen aan als die minstens 10 procentpunt verschuift, zodat er niet elke
dag kosten worden gemaakt. Aandelen, metalen en valuta laat hij met rust: daar kost elke
order minstens €1,25, en bij een potje van ~€1.000 eten kleine bijstellingen de winst op.

De beweeglijkheid komt uit de curves die de huidige regels op echte koersen hadden gehad
(dezelfde als in ``jplh backtest --desks``). Zo kijkt de directeur alleen terug, nooit vooruit,
en is live precies wat er getest is. De spelregel geldt ook hier: hij staat aan omdat hij in
de backtest won op Sharpe en diepste daling (zie ``risk_lines``)."""

from __future__ import annotations

import math

from jplh.backtest import metrics
from jplh.deskbacktest import desk_returns

WING = ("crypto", "meme")   # de afdelingen die de directeur bijstuurt
TARGET_VOL = 0.40           # gewenste beweeglijkheid van de vleugel per jaar
VOL_DAYS = 60               # over zoveel dagen meten
STEP = 0.10                 # pas aanpassen als de stand zoveel verschuift
MIN_EXPOSURE = 0.25         # nooit verder terug dan een kwart in de markt
MOVE_COST = 0.005           # kosten van verschuiven (crypto: ~0,35% handelskosten, ruim genomen)
REBALANCE_DAYS, BAND = 91, 0.10   # de holding zelf: elk kwartaal terug naar de vaste verdeling


def realized_vol(rets: list[float], days: int = VOL_DAYS) -> float | None:
    """Beweeglijkheid per jaar over de laatste ``days`` dagrendementen."""
    w = rets[-days:]
    if len(w) < min(days, 20):
        return None
    m = sum(w) / len(w)
    return math.sqrt(sum((x - m) ** 2 for x in w) / len(w)) * math.sqrt(365)


def wanted(wing_rets: list[float]) -> float:
    """Hoeveel van de vleugel in de markt hoort, alleen op basis van rendementen t/m gisteren."""
    vol = realized_vol(wing_rets)
    if not vol:
        return 1.0
    return max(MIN_EXPOSURE, min(1.0, TARGET_VOL / vol))


def next_exposure(current: float, want: float) -> float:
    """De stand verschuift alleen bij een flinke verandering, of terug naar volledig."""
    if abs(want - current) >= STEP or (want == 1.0 and current != 1.0 and abs(want - current) > 0.02):
        return round(want, 3)
    return current


def simulate(result: dict, shares: dict[str, float], director: bool = True) -> dict | None:
    """Speelt de holding na zoals live (vaste verdeling, elk kwartaal terug), met of zonder
    directeur. Geeft de cijfers, de stand per dag en de dagrendementen van de vleugel."""
    days, rets = desk_returns(result)
    wing = [c for c in WING if c in rets]
    if len(rets) < 2 or not wing or not days:
        return None
    total = sum(shares.get(c, 0) for c in rets)
    w = {c: shares.get(c, 0) / total for c in rets}
    ww = sum(w[c] for c in wing)
    val, e, eq, stand, wing_rets, moved = dict(w), 1.0, [], [], [], 0.0
    for k, d in enumerate(days):
        if director:
            new = next_exposure(e, wanted(wing_rets))
            if new != e:
                part = sum(val[c] for c in wing) * abs(new - e) / e
                moved += abs(new - e)
                for c in wing:
                    val[c] -= part * MOVE_COST * val[c] / sum(val[x] for x in wing)
                e = new
        for c in rets:
            val[c] *= 1 + (e if c in wing else 1.0) * rets[c][k]
        tot = sum(val.values())
        wing_rets.append(sum(rets[c][k] * w[c] for c in wing) / ww if ww else 0.0)
        if k and k % REBALANCE_DAYS == 0:
            target = {c: tot * w[c] for c in rets}
            if not all(target[c] and abs(val[c] / target[c] - 1) <= BAND for c in rets):
                tot -= sum(abs(target[c] - val[c]) for c in rets) / 2 * MOVE_COST
                val = {c: tot * w[c] for c in rets}
        eq.append(tot)
        stand.append((d, e))
    dr = [b / a - 1 for a, b in zip([1.0] + eq, eq)]
    m = metrics(dr, 0, 0, 0, 365)
    return {"return": m.total_return, "sharpe": m.sharpe, "max_dd": m.max_drawdown, "since": days[0],
            "days": len(days), "stand": stand, "wing_rets": wing_rets, "moved": moved}


def wins(base: dict, with_dir: dict) -> bool:
    """Spelregel: beter op Sharpe (+0,05) en niet dieper gezakt dan zonder directeur."""
    return with_dir["sharpe"] > base["sharpe"] + 0.05 and with_dir["max_dd"] <= base["max_dd"] + 0.01


def risk_lines(result: dict, shares: dict[str, float]) -> list[str]:
    """Stukje voor het backtest-rapport."""
    base, d = simulate(result, shares, False), simulate(result, shares, True)
    if not base or not d or base["days"] < VOL_DAYS + 30:
        return []
    return ["", f"## Risicodirecteur (crypto + memes samen, sinds {base['since']})", "",
            f"Doel: {TARGET_VOL:.0%} beweeglijkheid per jaar voor {' + '.join(WING)}, gemeten over {VOL_DAYS} dagen, "
            f"aanpassen bij {STEP:.0%} verschil, verschuiven kost {MOVE_COST:.1%}. "
            "De rest van de holding blijft zoals live. ✅ = wint volgens de spelregel.", "",
            "| Hele holding | Rendement | Sharpe | Max daling |", "|---|---:|---:|---:|",
            f"| zonder directeur (live) | {base['return']:+.1%} | {base['sharpe']:.2f} | {-base['max_dd']:.1%} |",
            f"| met directeur{' ✅' if wins(base, d) else ''} | {d['return']:+.1%} | {d['sharpe']:.2f} | {-d['max_dd']:.1%} |"]


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 20:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def assess(result: dict, shares: dict[str, float], current: float | None, now) -> dict | None:
    """De stand van vandaag voor de live holding, Jarvis en het dashboard."""
    base, d = simulate(result, shares, False), simulate(result, shares, True)
    if not base or not d:
        return None
    vol = realized_vol(d["wing_rets"])
    # Dezelfde weg als in de backtest: verder vanaf de stand die de directeur daar had.
    exposure = next_exposure(d["stand"][-1][1], wanted(d["wing_rets"]))
    ok = wins(base, d)
    if not ok:          # spelregel: verliest hij de backtest, dan stuurt hij niet bij
        exposure = 1.0
    days, rets = desk_returns(result)
    corr = _corr(rets["crypto"][-VOL_DAYS:], rets["meme"][-VOL_DAYS:]) if {"crypto", "meme"} <= set(rets) else None
    desk_vol = {c: round(v, 4) for c, r in rets.items() if (v := realized_vol(r)) is not None}
    pack = lambda m: {"return": m["return"], "sharpe": m["sharpe"], "max_dd": m["max_dd"]}
    return {"computed_at": now.isoformat(), "wing": list(WING), "target": TARGET_VOL, "vol_days": VOL_DAYS,
            "vol": vol, "want": round(wanted(d["wing_rets"]), 3), "exposure": exposure,
            "changed": current is not None and abs(current - exposure) > 1e-9,
            "crypto_meme_corr": corr, "desk_vol": desk_vol,
            "backtest": {"base": pack(base), "director": pack(d), "days": d["days"], "wins": ok,
                         "since": d["since"].isoformat()},
            "history": [[x.isoformat(), e] for x, e in d["stand"][-180:]]}
