# NEXUS AI

Het Command Center van JP-libau Holding: één plek voor alle bots. NEXUS leest de echte paper-stand
van de holding, labelt elke waarde naar herkomst, en voegt de besturing toe die over alle bots
heen hoort: handelsmodus, noodstop, een Risk Guardian met vetorecht en een audit-log.

**Winst is niet gegarandeerd.** NEXUS verzint geen koersen, trades, rendementen of AI-zekerheid.
Zonder data toont het `UNAVAILABLE` en geen getal. **Live handelen staat uit en bestaat in deze
versie niet**; zelfs aanzetten via de API wordt geweigerd.

- Architectuur: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Databronnen en API's: [docs/DATA-SOURCES.md](docs/DATA-SOURCES.md)
- Databaseschema: [docs/schema.sql](docs/schema.sql)
- Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)

## Starten

Python 3.11+ en Node 20+.

```bash
# 1. Backend (vanaf de root van de repo)
python -m venv .venv && source .venv/bin/activate
pip install -e . -e "nexus/backend[dev]"

# Echte paper-stand: haal de paper-data-branch binnen
git worktree add ../paper-data origin/paper-data
NEXUS_HOLDING_HOME=../paper-data NEXUS_ADMIN_TOKEN=kies-een-lang-geheim nexus-api
#   of een expliciete demo met nep-koersen:  NEXUS_DEMO=1 nexus-api

# 2. Frontend (tweede terminal)
cd nexus/web && npm install && npm run dev
# open http://localhost:3000
```

Of alles in Docker (met TimescaleDB): `NEXUS_DB_PASSWORD=... docker compose -f nexus/docker-compose.yml up --build`.

Tests: `cd nexus/backend && pytest` en `cd nexus/web && npm run build`.

## Wat er nu werkt (fase 1)

| Onderdeel | |
|---|---|
| Command Center | vermogen, gerealiseerd/ongerealiseerd, kosten, vermogens- en drawdowncurve, verdeling, posities, marktregime, risicogebruik, Council-status, voorstellen, bevindingen, beslissingen, markten, verbindingen |
| Herkomstlabels | LIVE · DELAYED · HISTORICAL · SIMULATED · UNAVAILABLE op elk paneel en elke koers |
| Risk Guardian | 11 grenzen (conservatief, alleen strenger), veto per voorstel met elke check, "geen trade" altijd mogelijk |
| Noodstop | knop met bevestiging; zet ook het KILL-bestand van de holding; opheffen alleen met admin-token |
| Modi | research / paper; live wordt geweigerd met de live-poort |
| Voorstellen | `POST /api/proposals`: verplicht formaat, idempotent, oordeel opgeslagen, nooit uitgevoerd |
| Pagina's | 15 routes; Council, Radar, Meme Scanner, Portfolio, Risk, Journal en Settings met echte data, de rest toont eerlijk wat er al is en wat komt |

## API

| Methode | Pad | |
|---|---|---|
| GET | `/api/health` | status, omgeving, noodstop |
| GET | `/api/command-center` | alles voor het dashboard |
| GET | `/api/agents` · `/api/risk` · `/api/connections` · `/api/controls` · `/api/audit` · `/api/proposals` | |
| POST | `/api/controls/kill` | noodstop aan (geen token nodig) |
| POST | `/api/controls/kill/release` | noodstop uit (admin-token) |
| POST | `/api/controls/mode` | research/paper (admin-token); live → 403 |
| POST | `/api/proposals` | voorstel laten beoordelen |

Interactieve docs: http://127.0.0.1:8000/docs
