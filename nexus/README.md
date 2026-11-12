# NEXUS AI

*Intelligence Behind Every Trade.*

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

## Wat er nu werkt (persoonlijke MVP)

| Systeem | Wat | Echt of gesimuleerd |
|---|---|---|
| Command Center | stand van de holding-bots en het NEXUS paper-account, risico, regime, markten, verbindingen | echte paper-stand |
| Marktdata | één laag voor alle bronnen met bron, tijd, munt, versheid, sessie en kwaliteit (`/api/market/series`) | Bitvavo en Yahoo echt; CoinGecko, Polygon, FMP, FRED nog niet gekoppeld |
| Strategy Lab | 5 geversioneerde strategieën met regels en een backtest: in-/out-of-sample, 5 vakken, regimes, koop-en-houd, kosten, spread, liquiditeitsgrens | echte dagkoersen (HISTORICAL) |
| Paper trading | voorstel → Risk Guardian → order → vulling (deels mogelijk) → positie → waardering → reconciliatie | gesimuleerde vullingen op echte, vertraagde koersen |
| Risk Guardian | 11 grenzen, veto op elk voorstel, noodstop | echt |
| Database | 22 tabellen (gebruikers, organisaties, accounts, brokers, assets, marktdata, strategieën, backtests, voorstellen, orders, vullingen, posities, waarderingen, risicobeleid, AI-rapporten, agentbesluiten, audit, abonnementen, facturen) met Alembic | echt (SQLite of PostgreSQL) |
| Realtime | WebSocket `/ws/events` (noodstop, modus, voorstellen, vullingen) + achtergrondworker | echt, in één proces |
| SaaS-admin | plannen €19/€59/€149 (inactief), juridische poort, uptime en fouten | geen klanten, geen betaalkoppeling |

Nog niet gebouwd: AI-agents op een taalmodel, inloggen en meerdere gebruikers, Stripe, Redis (nodig zodra er
meer dan één API-proces draait), live broker-adapters, publieke website. Zie [docs/ROADMAP.md](docs/ROADMAP.md).

Meer: [docs/OPERATIONS.md](docs/OPERATIONS.md) (uitrol, geheimen, monitoring, terugdraaien) en
[docs/SECURITY.md](docs/SECURITY.md) (beveiliging, compliance, incidenten).

## API

| Methode | Pad | |
|---|---|---|
| GET | `/api/health` | status, omgeving, noodstop |
| GET | `/api/command-center` | alles voor het dashboard |
| GET | `/api/agents` · `/api/risk` · `/api/connections` · `/api/controls` · `/api/audit` · `/api/proposals` | |
| POST | `/api/controls/kill` | noodstop aan (geen token nodig) |
| POST | `/api/controls/kill/release` | noodstop uit (admin-token) |
| POST | `/api/controls/mode` | research/paper (admin-token); live → 403 |
| POST | `/api/proposals` | voorstel laten beoordelen (tegen het paper-account) |
| POST | `/api/proposals/{id}/execute` | goedgekeurd voorstel als paper-order (alleen paper-modus) |
| GET | `/api/paper` · POST `/api/paper/step` · POST `/api/paper/orders/{id}/cancel` | paper-account, orders, vullingen, reconciliatie |
| GET | `/api/market/providers` · `/api/market/series?symbol=BTC-EUR&interval=1h` | marktdata met herkomst |
| GET | `/api/strategies` · POST `/api/backtests` · GET `/api/backtests/{id}` | Strategy Lab |
| GET | `/api/admin/overview` | SaaS-administratie |
| WS | `/ws/events` | realtime gebeurtenissen |

Interactieve docs: http://127.0.0.1:8000/docs
