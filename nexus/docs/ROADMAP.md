# Roadmap

Elke fase eindigt met werkende software en tests. Live handelen wordt nooit automatisch aangezet.

| Fase | Inhoud | Klaar als |
|---|---|---|
| **1 · Fundament** (klaar, PR #25) | architectuur, API, Command Center, 15 pagina's, Risk Guardian, noodstop, modi, herkomstlabels, audit-log, tests, docker | app start, dashboard toont echte paper-stand, noodstop werkt, live staat uit |
| 2 · Marktintelligentie | streaming (Bitvavo WS), candlestick-terminals met indicatoren, fundamentals-bron, macro (FRED), meme-veiligheidschecks (contract, honeypot, houders), WebSocket naar de frontend | elke terminal toont echte data met labels; meme-tokens zonder checks worden afgewezen |
| 3 · AI Expert Council | Anthropic-provider achter een abstractie, 13 agents met gestructureerde output, bewijs per bewering, tegenargumenten, CIO-synthese, voorstellen via de Guardian, besluittijdlijn | elk voorstel herleidbaar tot data en agent-output; geen ongekalibreerde zekerheid als kans getoond |
| 4 · Kwantitatief onderzoek | strategie-register met versies, backtests vanuit NEXUS, Monte Carlo, betrouwbaarheidsintervallen, parametergevoeligheid, prestatietabel | een strategie kan alleen door naar paper na walk-forward + out-of-sample + toeval-toets |
| 5 · Paper trading | NEXUS-voorstellen paper uitvoeren, orderlevenscyclus, idempotentie, gedeeltelijke vullingen, execution monitor | paper-trades kloppen met de boekhouding; reconciliatie-tests |
| 6 · Live-gereedheid | broker-adapters, sleutelrechten-audit, circuit breakers, noodsluiting van posities, deployment-checks | alle poortchecks groen; daarna alleen live met jouw schriftelijke activatie |
| 7 · Optimalisatie | betrouwbaarheid, latency, UX, onderzoekskwaliteit | doorlopend |

Realistisch: fase 2 en 3 zijn elk een paar werksessies. Fase 6 hangt af van welke broker je kiest en
van minstens enkele maanden paper-resultaten die de backtest bevestigen.

## Stand na de MVP-mijlpaal (prompt 2.0)

Gedaan uit de uitvoeringsvolgorde: repo bekeken, architectuur en roadmap, ontwerpsysteem in de merkkleuren,
Command Center, databaseschema met migraties (22 tabellen), frontend aan backend, marktdata-laag met echte
adapters (Bitvavo, Yahoo), 5 deterministische strategieën, backtest-workflow, paper trading met
gedeeltelijke vullingen en reconciliatie, tests (backend + build), documentatie.

## Stand na Master Prompt 3.1 (Evolution Lab)

Gedaan: diagnose van IWDA (attributie, 10 vragen), Alpha Research Engine, champion-challenger met 8 poorten en
afgesloten holdout, multi-timeframe data, besluitgeheugen en leerlus met hypothesen en modelregister, AI Expert
Council op Claude met debat en kalibratiegewichten, nieuwsintelligentie, Grok-vergelijking, geplande taken,
hash-keten in het auditlog, Evolution Lab-dashboard. Resultaten: [research/RESULTS.md](../research/RESULTS.md).

Volgende onderzoeksstappen staan in RESULTS.md. Volgende bouwstappen:
1. Langere en intraday-geschiedenis ophalen in CI (het netwerk werkt daar) en de ontdekking op 1h/4h draaien.
2. Bronnen voor marktverwachtingen (consensus) en funding/open interest koppelen, zodat event- en
   crypto-families niet langer `niet beschikbaar` zijn.
3. **Inloggen en tenants**: argon2-wachtwoorden, sessies, wachtwoordherstel, MFA (TOTP), rollen; elke query per `org_id`.
4. **Redis + aparte worker**: pub/sub voor events en een jobqueue, zodat de API meerdere processen kan draaien.
5. **Marktdata uitbreiden**: streaming (Bitvavo WebSocket), gelicentieerde aandelenbron (keuze Polygon/FMP),
   CoinGecko, FRED, meme-veiligheidschecks.
6. **Stripe en onboarding** (pas na de juridische toets): abonnementen, proef, facturen, gebruiksmeting.
7. **Publieke website**: landing, functies, prijzen, beveiliging, FAQ, documentatie, contact.
8. **Live-gereedheid**: broker-adapters met permissiecheck, herstel na onderbreking, positie-reconciliatie met de broker.
