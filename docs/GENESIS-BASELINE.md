# GENESIS · Baseline (E0.1)

Vastgesteld op 13-11-2026 rond 16:45 (Amsterdam), vóór de wijzigingen van Milestone E. Alles hieronder is in deze sessie
zelf gemeten. Niets is overgenomen uit eerdere rapporten zonder controle.

## Repository en merge-staat

| Controle | Uitkomst |
|---|---|
| PR #31 (Milestone D) | **gemerged** in `main` (merge-commit `a126846`) |
| PR #30 (Milestone C) | gemerged (`801dc8d`), zit in de geschiedenis van `main` |
| Werkboom | schoon. Branch `claude/project-thread-gyycqq` opnieuw gestart vanaf `origin/main` (alleen al gemergde geschiedenis) |
| Milestone C- en D-code aanwezig | ja: `activation.py`, `workflow.py`, `debate.py`, `ai_eval.py` (C); `workstation.py`, `apex_api.py`, `/decisions`, `/pulse` (D) |

## Tests en build

| Suite | Uitkomst |
|---|---|
| NEXUS-backend (`nexus/backend`, pytest) | **182 geslaagd**, 0 gefaald |
| Holding-onderzoek (`tests/`, pytest) | **138 geslaagd**, 0 gefaald |
| Web: eslint | schoon |
| Web: tsc | schoon |
| Web: `next build` | geslaagd, 26 statische routes |

## Operationele configuratie (alleen namen, nooit waarden)

| Variabele | Staat |
|---|---|
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | **niet ingesteld** |
| `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY` | niet ingesteld |
| X-bearer-token | niet ingesteld |
| `NEXUS_SEC_USER_AGENT` (vereist door SEC/EDGAR) | niet ingesteld |
| `NEXUS_AI_DAILY_BUDGET_USD` | niet ingesteld, dus de standaard **$3,00 per dag** |
| Standaard Anthropic-model | `claude-opus-5-5` ($4 / $20 per miljoen tokens in/uit) |

## Netwerk in deze ontwikkelomgeving

De sessie draait op de omgeving **Default** (beperkt netwerk, geen eigen hosts toegestaan). Per host getest via de
uitgaande proxy. Een "403 op CONNECT" is een **beleidsweigering van de omgeving**, niet een fout van de bron.

| Host | Uitkomst |
|---|---|
| api.anthropic.com | bereikbaar (HTTP 401 zonder sleutel: de host werkt, er is alleen geen sleutel) |
| generativelanguage.googleapis.com | bereikbaar (HTTP 404 op de wortel) |
| www.federalreserve.gov, www.ecb.europa.eu, www.bls.gov, www.sec.gov | **geblokkeerd** (proxy 403 op CONNECT) |
| status.kraken.com, status.coinbase.com | **geblokkeerd** |
| api.gopluslabs.io, api.dexscreener.com | **geblokkeerd** |
| api.x.com, api.openai.com, api.x.ai | **geblokkeerd** |
| api.bitvavo.com, query1.finance.yahoo.com | **geblokkeerd** |

Providerprobes van NEXUS zelf (`providers.probe`): anthropic, openai, gemini, xai en x_api geven `credentials_missing`;
goplus, dexscreener, yahoo en bitvavo geven `network_blocked`.

Er bestaat al een tweede cloudomgeving, "JP-Libau Holding NEXUS (data-feeds)", die precies deze 14 hosts toestaat.
Deze lopende sessie kan daar niet naartoe verhuizen. De operationele tests (Gate 2) moeten dus draaien in een nieuwe
sessie op die omgeving, met een sleutel die de CEO daar zelf instelt. Zie `GENESIS-ACTIVATION.md`.

## Wat werkt, per poort (stand vóór E)

| Onderdeel | Gate 1 (engineering) | Gate 2 (operationeel) | Gate 3 (waarde) |
|---|---|---|---|
| AI Gateway (routering, fallback, budget, stroomonderbreker) | TESTED | BLOCKED (geen sleutel) | — |
| Council en debat | TESTED | BLOCKED | — |
| News Reactor | TESTED (fixtures) | BLOCKED (feeds geblokkeerd) | regels 28/30 op een eigen set, **niet onafhankelijk** |
| X Intelligence | TESTED | BLOCKED (geen token, host geblokkeerd) | — |
| GoPlus / DexScreener | TESTED | BLOCKED (host geblokkeerd) | — |
| Event-workflow (C5) | TESTED | SIMULATED (één fixture-spoor) | — |
| Neural Core / Decision Theater | TESTED | SIMULATED (alleen fixture-activiteit) | — |
| Koersdata (opgeslagen) | TESTED | CONNECTED in het verleden; nu vertraagd (laatste dag 11-11-2026) | — |
| IWDA-strategieën | TESTED | — | **niet beter dan koop-en-houd** |
| Holdout (vanaf 12-11-2026) | TESTED | actief, niet aangeraakt | — |
| Live handelen | — | **uit** | — |

## Open beveiligings- en integratierisico's (bekend)

1. Eén gedeeld admin-token voor alle CEO-acties. Er bestaat een operator-token, maar zonder aparte onderzoeksrol.
2. Rate limiting in het geheugen: reset bij een herstart en is niet gedeeld tussen processen.
3. SQLite als ontwikkelopslag.
4. Geen gebruikersaccounts of sessies: de authenticatie is niet productierijp.
5. De Anthropic-adapter negeert `max_tokens` uit het routeringsbeleid en `NEXUS_ANTHROPIC_MODEL`: het model staat vast in de code en de uitvoer op 8000 tokens. **Gevonden in E0.1, opgelost in E0.2.**
6. AI-onderzoek kan niet apart worden gepauzeerd: alleen de noodstop voor handelen bestaat.
