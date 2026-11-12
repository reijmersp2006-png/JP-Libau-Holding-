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

Volgende mijlpalen, in deze volgorde:
1. **AI Expert Council op Claude**: provider-abstractie, per agent input/output-schema, toegestane tools,
   foutafhandeling, logging naar `agent_decisions`, evaluatietests. CIO-synthese levert alleen voorstellen
   aan de Risk Guardian; geen pad naar orders.
2. **Inloggen en tenants**: argon2-wachtwoorden, sessies, wachtwoordherstel, MFA (TOTP), rollen; elke query per `org_id`.
3. **Redis + aparte worker**: pub/sub voor events en een jobqueue, zodat de API meerdere processen kan draaien.
4. **Marktdata uitbreiden**: streaming (Bitvavo WebSocket), gelicentieerde aandelenbron (keuze Polygon/FMP),
   CoinGecko, FRED, meme-veiligheidschecks.
5. **Stripe en onboarding** (pas na de juridische toets): abonnementen, proef, facturen, gebruiksmeting.
6. **Publieke website**: landing, functies, prijzen, beveiliging, FAQ, documentatie, contact.
7. **Live-gereedheid**: broker-adapters met permissiecheck, herstel na onderbreking, positie-reconciliatie met de broker.
