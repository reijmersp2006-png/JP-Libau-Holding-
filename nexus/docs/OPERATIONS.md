# Uitrol, geheimen, monitoring en terugdraaien

## Uitrol (persoonlijke MVP)
1. `docker compose -f nexus/docker-compose.yml up --build` (API, web, TimescaleDB), of lokaal volgens `nexus/README.md`.
2. De API brengt de database bij het starten zelf naar de nieuwste Alembic-migratie (`nexus.db.upgrade`).
   Handmatig: `cd nexus/backend && alembic -x ... upgrade head` met `sqlalchemy.url` op de juiste database.
3. Controle na uitrol: `GET /api/health` geeft `status: ok`, `live_trading: false`; het Command Center laadt.

## Geheimen
- Alleen via omgevingsvariabelen of de secret store van het platform (GitHub Actions secrets, Docker secrets).
  Nooit in de repo, nooit in `NEXT_PUBLIC_*`.
- `NEXUS_ADMIN_TOKEN`: lang en willekeurig (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- Broker-sleutels (fase 7): alleen een verwijzing in `broker_connections.credentials_ref`; de sleutel zelf in
  een secret store, zonder opname- en hefboomrecht, met IP-whitelist.

## Monitoring
- Gestructureerde JSON-logs op stdout (`nexus.main.JsonFormatter`).
- `GET /api/health` voor uptime-checks; `GET /api/admin/overview` toont verzoeken en serverfouten sinds start.
- Elke besturingsactie, order en vulling staat in `audit_log`.
- `GET /api/paper` geeft de reconciliatie; een verschil hoort een alarm op te leveren (Jarvis-koppeling volgt).

## Terugdraaien
- Code: vorige image of vorige commit uitrollen.
- Database: `alembic downgrade -1` (elke migratie heeft een downgrade). Maak vóór elke migratie in productie een back-up.
- Noodgeval: noodstop (`POST /api/controls/kill` of de knop) stopt alle paper-orders én de holding-bot in de gekoppelde map.
