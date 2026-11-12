# NEXUS AI · systeemarchitectuur

NEXUS AI is de besturings- en analyselaag boven op de JP-libau Holding. De holding (`jplh`, Python,
in `src/jplh`) bestaat al en doet het echte werk: koersen verzamelen, vijf afdelingen die op papier
handelen, een risico-afdeling met vetorecht, walk-forward-backtests, een schaduw-arena en de
Academie. NEXUS bouwt daar niet naast maar bovenop: één API, één Command Center, één Risk Guardian
voor alle bots.

## Lagen

```
┌──────────────────────────── nexus/web (Next.js, TypeScript, Tailwind) ─────────────────────────────┐
│ Command Center · Council · Radar · Terminals · Strategy Lab · Backtesting · Risk · Journal · Settings│
│ Alleen lezen + noodstop. Geen sleutels, alleen NEXT_PUBLIC_NEXUS_API.                              │
└───────────────────────────────────────────────┬─────────────────────────────────────────────────────┘
                                                │ HTTPS / JSON (fase 2: WebSocket-stream)
┌───────────────────────────── nexus/backend (FastAPI) ─────────────────────────────────────────────┐
│ app.py        routes, admin-token, rate-limit, CORS, audit                                       │
│ bridge.py     leest de holding via jplh (build_state, desks, ledger), cache 30 s, alleen lezen     │
│ provenance.py LIVE / DELAYED / HISTORICAL / SIMULATED / UNAVAILABLE                               │
│ guardian.py   Risk Guardian: veto op elk voorstel, grenzen alleen strenger                         │
│ proposals.py  verplicht voorstel-formaat (exit, tegenargumenten, kalibratie, max. verlies)         │
│ controls.py   modus research/paper (live bestaat niet), noodstop = KILL-bestand, live-poort        │
│ agents.py     13 rollen met echte status (operational/partial/not_built)                           │
│ db.py         SQLAlchemy: system_state, audit_log, trade_proposals, risk_evaluations              │
└───────────────┬───────────────────────────────────────────────┬───────────────────────────────────┘
                │ Python-import                                 │ SQLite nu, PostgreSQL/Timescale later
┌───────────────▼──────────── jplh (bestaand) ──────────┐  ┌──────▼──────── NEXUS-opslag ────────────┐
│ data/ bitvavo, yahoo, ecb, dexscreener, demo           │  │ besturing, audit, voorstellen, oordelen │
│ risk.py · broker.py (paper) · ledger · desks · arena   │  └─────────────────────────────────────────┘
│ backtest · deskbacktest · academy · coach · jarvis     │
│ data/holding.sqlite3 + data/desks/*.sqlite3 (paper)    │◄── GitHub Actions: elk uur een paper-ronde,
└────────────────────────────────────────────────────────┘    stand op de branch `paper-data`
```

## Besluitvormingsketen

| Stap | Waar nu | Status |
|---|---|---|
| Marktdata ophalen | `jplh.collect` + adapters | draait (uurkoersen, DELAYED) |
| Datakwaliteit | `jplh.risk` koers_vers (max 3 uur), `nexus.provenance` | draait |
| Marktregime | `Desk.regime` (200-dagen), Risicodirecteur | draait |
| Kansen | strategieën per afdeling, verkenners | draait |
| Agent-analyse | `nexus.council` (13 agents, Claude; quant/risk/auditor deterministisch) | draait op verzoek en dagelijks, binnen dagbudget; zonder sleutel `unavailable` |
| Strategie-toets | `jplh backtest --desks`, arena, Academie | draait (CLI) |
| Portefeuille-impact | Risicodirecteur, `nexus.guardian` | draait |
| Risk Guardian | `jplh.risk` (paper-bot) + `nexus.guardian` (voorstellen) | draait |
| Uitvoeringsplan | `nexus` execution | fase 5 |
| Paper / live | `jplh.broker` paper; live bestaat niet | paper draait |
| Monitoring | logboek, Jarvis, NEXUS audit | draait |

Regels die nergens omheen kunnen:
1. Niets wordt uitgevoerd zonder goedgekeurd oordeel van de Risk Guardian.
2. De noodstop blokkeert alles, ook verkopen. Aanzetten mag altijd; opheffen vraagt het admin-token.
3. `set_mode("live")` geeft altijd een weigering met de live-poort. Er is geen live adapter.
4. Geen hefboom, geen short, geen derivaten: het voorstel-formaat kent alleen `buy` en `sell` van bezit.
5. Ontbrekende data levert `UNAVAILABLE` op en geen getal. Er wordt nooit een koers ingevuld.
6. Een zekerheidsscore heet alleen "gekalibreerd" met een statistische methode; een LLM-score nooit.

## Evolution Lab (Master Prompt 3.1)

```
stats.py      bootstrap (blok), probabilistische en gedefleerde Sharpe, Monte Carlo-daling, verwachtingswaarde
audit.py      attributie in log-rendement (buiten de markt, kosten, wisseldagen, in de markt), oorzaak, regime
datasets.py   1d/4h/1h/15m/5m, omrekening naar euro met de koers die op dat moment bekend was
alpha.py      strategiefamilies (trend, mean reversion, portefeuille, crypto; event/funding = niet beschikbaar)
              fractionele gewichten 0-1, uitvoering op de volgende open, kosten + spread + slippage
              walk-forward per vak, laatste 20% = holdout, holdout-register (jsonl, alleen toevoegen)
champion.py   kampioen tegen uitdagers op dezelfde vakken; poorten 1-8; holdout pas open na 1,2,4,5,6
evolution.py  besluitgeheugen (uitgevoerd/afgewezen/gemist), uitkomst na 1/5/20 dagen, fout-tags,
              hypothesen, toets, kandidaat in het modelregister (nooit zelf kampioen)
council.py    onafhankelijk oordeel → debat → CIO-besluit; gewichten uit Brier; Risk Guardian-veto bindend
news.py       officiële feeds (Fed, ECB, BLS, SEC), feit/speculatie, koersreactie in σ, event-study
external.py   import van een ander systeem (CSV/JSON), vergelijking op gelijk kapitaal en periode
jobs.py       uur/dag/week/maand-taken in een eigen achtergrondtaak, met AI-kosten per run
evolution_api.py  alle /api/evolution, /api/council, /api/news, /api/external, /api/jobs routes
```

Leerlus: observeren → besluiten → uitvoeren of afwijzen → meten → analyseren → leren → valideren → verbeteren.
Wat leren mag: hypothesen maken, toetsen, een kandidaat registreren. Wat leren niet mag: een kampioen vervangen,
live aanzetten of een risicogrens wijzigen. Promoveren is een admin-actie die de arena-poorten opnieuw toetst;
kampioen worden vraagt ook 30 paperdagen. Het auditlog is een hash-keten (`/api/audit/verify`).

## Waarom bovenop jplh en niet een nieuw systeem

De holding heeft al ~6.000 regels geteste code, echte paper-resultaten sinds 9 november 2026 en een
spelregel (een wijziging gaat pas live als ze de afdelingen-backtest wint). Opnieuw beginnen zou die
validatie weggooien. NEXUS hergebruikt daarom de adapters, de risico-afdeling, de boekhouding en de
backtests, en voegt toe wat over alle bots heen nodig is.

## Beveiliging

- Sleutels alleen via omgevingsvariabelen op de server; de API geeft alleen "aanwezig ja/nee" terug.
- Exchange-sleutels (fase 6) zonder opname- en hefboomrecht; DEX-handel via wallet-signing, nooit
  opgeslagen private keys.
- Schrijvende endpoints: rate-limit per IP, Pydantic-validatie, admin-token met constante-tijd-vergelijking.
- Audit-log is alleen-toevoegen. Elke modus- of noodstopwijziging en elk voorstel staat erin.
- CORS alleen voor de eigen frontend.
