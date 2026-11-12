"""De AI Expert Council: welke van de 13 rollen bestaan al echt, en waar draait dat op.

Er wordt hier geen agent-activiteit verzonnen. Een rol is:
- ``operational``: draait nu, aantoonbaar, op een bestaand onderdeel van de holding;
- ``partial``: een deel van de taak draait (staat in ``covers``), de rest (``missing``) niet;
- ``not_built``: bestaat nog niet. Er wordt dan ook geen analyse getoond.
``last_activity`` komt uit echte tijdstempels in de data, of is leeg.
LLM-agents (Anthropic API) komen in fase 3, met gestructureerde output en bewijs per bewering.
"""

from __future__ import annotations

from nexus.bridge import Snapshot

AGENTS: list[dict] = [
    {"id": "cio", "n": 1, "name": "Chief Investment Officer", "status": "not_built", "phase": 3,
     "backed_by": None, "covers": [],
     "missing": ["agents coördineren", "conflicten afwegen", "eindvoorstel opstellen"]},
    {"id": "quant", "n": 2, "name": "Quantitative Researcher", "status": "partial", "phase": 4,
     "backed_by": "jplh.backtest, jplh.deskbacktest, jplh.academy",
     "covers": ["walk-forward-backtests", "strategievergelijking per afdeling", "toeval-toets (blok-bootstrap)"],
     "missing": ["factormodellen", "volatiliteitsmodellen", "Monte Carlo"]},
    {"id": "technical", "n": 3, "name": "Technical Analyst", "status": "operational", "phase": 2,
     "backed_by": "jplh.strategies, jplh.desks",
     "covers": ["trend (gemiddelden)", "momentum", "uitbraak", "terugkeer naar gemiddelde", "200-dagen-marktweer"],
     "missing": ["RSI/MACD/VWAP", "volumeprofiel", "steun/weerstand"]},
    {"id": "fundamental", "n": 4, "name": "Fundamental Equity Analyst", "status": "not_built", "phase": 2,
     "backed_by": None, "covers": [],
     "missing": ["bron voor jaarcijfers en winstverwachtingen (licentie nodig)"]},
    {"id": "crypto", "n": 5, "name": "Crypto Intelligence Analyst", "status": "partial", "phase": 2,
     "backed_by": "jplh.data.bitvavo, jplh.scouts",
     "covers": ["koersen en volume (Bitvavo)", "volume- en koersalarmen"],
     "missing": ["on-chain", "exchange-stromen", "funding/open interest", "liquidaties", "whales"]},
    {"id": "meme", "n": 6, "name": "Meme Coin Specialist", "status": "partial", "phase": 2,
     "backed_by": "jplh.data.dexscreener (alleen kijken)",
     "covers": ["DexScreener-radar", "rode vlaggen: lage liquiditeit, jonge pair, extreme beweging"],
     "missing": ["contract- en honeypotcheck", "houderverdeling", "dev-wallets", "liquidity lock"]},
    {"id": "macro", "n": 7, "name": "Macro Economist", "status": "partial", "phase": 2,
     "backed_by": "jplh.data.ecb, jplh.scouts (verkenners)",
     "covers": ["ECB-wisselkoersen", "VIX, rente en indexen volgen"],
     "missing": ["economische kalender", "centrale-bankbesluiten", "risk-on/off-model"]},
    {"id": "sentiment", "n": 8, "name": "Sentiment Intelligence Analyst", "status": "not_built", "phase": 3,
     "backed_by": None, "covers": [], "missing": ["toegestane nieuws- en sociale bronnen", "onderscheid feit/gerucht"]},
    {"id": "risk", "n": 9, "name": "Risk Guardian", "status": "operational", "phase": 1,
     "backed_by": "jplh.risk (paper-bot) + nexus.guardian (voorstellen)",
     "covers": ["vetorecht op elke order", "drawdown/dagverlies", "concentratie", "liquiditeit", "noodstop"],
     "missing": []},
    {"id": "execution", "n": 10, "name": "Execution Specialist", "status": "partial", "phase": 5,
     "backed_by": "jplh.broker (paper)",
     "covers": ["paper-vullingen met kosten en slippage per afdeling"],
     "missing": ["ordertypes", "timing", "live adapters (fase 6)"]},
    {"id": "portfolio", "n": 11, "name": "Portfolio Manager", "status": "operational", "phase": 1,
     "backed_by": "jplh.desks, jplh.riskdirector",
     "covers": ["verdeling over afdelingen", "kwartaal-herverdeling", "Risicodirecteur (doel-volatiliteit)"],
     "missing": ["correlatie- en risicobijdrage per positie"]},
    {"id": "auditor", "n": 12, "name": "Strategy Auditor", "status": "operational", "phase": 4,
     "backed_by": "jplh.arena, jplh.academy, jplh.coach",
     "covers": ["schaduw-arena", "live vs. backtest vergelijken", "vuistregels toetsen op eigen data"],
     "missing": ["parametergevoeligheid"]},
    {"id": "security", "n": 13, "name": "Cybersecurity & Compliance Officer", "status": "partial", "phase": 1,
     "backed_by": "nexus.controls",
     "covers": ["live-poort", "audit-log", "geen sleutels in frontend of repo"],
     "missing": ["sleutelrechten-audit bij exchanges", "wallet-signing", "jurisdictiechecks"]},
]


def _latest(feed: list[dict], **match) -> str | None:
    for f in feed:          # feed staat nieuw -> oud
        if all(f.get(k) in (v if isinstance(v, tuple) else (v,)) for k, v in match.items()):
            return f["ts"]
    return None


def council(snap: Snapshot | None) -> list[dict]:
    out = []
    feed = snap.state.get("feed", []) if snap else []
    risk = snap.state.get("risk") if snap else None
    activity = {
        "risk": _latest(feed, kind=("trade", "refused")),
        "technical": _latest(feed, kind=("trade", "selection")),
        "execution": snap.last_fill if snap else None,
        "meme": snap.radar_at if snap else None,
        "macro": _latest(feed, desk="scouts"),
        "crypto": _latest(feed, desk="scouts"),
        "portfolio": risk.get("computed_at") if risk else None,
        "auditor": (snap.state.get("arena") or {}).get("computed_at") if snap else None,
        "quant": (snap.state.get("academy") or {}).get("computed_at") if snap else None,
    }
    for a in AGENTS:
        item = dict(a)
        item["last_activity"] = activity.get(a["id"]) if a["status"] != "not_built" else None
        item["llm"] = False                      # nog geen enkele rol draait op een taalmodel
        out.append(item)
    return out


def summary(agents: list[dict]) -> dict:
    s = {"operational": 0, "partial": 0, "not_built": 0}
    for a in agents:
        s[a["status"]] += 1
    return s
