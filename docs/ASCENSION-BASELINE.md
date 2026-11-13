# NEXUS 5.0 "Ascension" · nulmeting (13 november 2026)

Labels: **IMPLEMENTED** (code staat er), **TESTED** (automatische tests slagen), **CONNECTED** (praat aantoonbaar
met een echte bron), **SIMULATED** (paper, demo of opgenomen antwoord), **NOT AVAILABLE** (ontbreekt sleutel,
netwerk of data). Alles hieronder is in deze sessie opnieuw gemeten; niets is overgenomen uit eerdere rapporten.

## 1. Controle van de Sentinel-claims (12 november)

| Claim | Gecontroleerd | Uitkomst |
|---|---|---|
| NEXUS Central: 19 rollen, 6 afdelingen | `central.ROLES` geteld, `/api/central/org` | Klopt. |
| Taakorkestratie en CEO-escalatie | `test_state_machine_*`, `test_plan_*` | Klopt (TESTED). |
| Briefing en beslissingstijdlijn | API getest; op een verse database leeg | Klopt; er is nog geen Council-run, dus de tijdlijn is leeg. |
| News Reactor heeft 0 live gebeurtenissen verwerkt | probe van alle 9 feeds | Klopt. De oorzaak is nu vastgesteld: de proxy van deze ontwikkelomgeving weigert de hosts (`network_blocked`). Voor SEC/EDGAR ontbreekt daarnaast `NEXUS_SEC_USER_AGENT`. |
| Geen X API-gegevens | probe | Klopt: `X_BEARER_TOKEN` ontbreekt, en `api.x.com` wordt hier ook geblokkeerd. |
| GoPlus en DexScreener niet verbonden | probe | Klopt: `network_blocked` (er is geen sleutel nodig). |
| Market Pulse gebruikt vertraagde dagdata | `/api/ops/health` | Klopt: de nieuwste dagkoers is 1,5 dag oud (DELAYED, geen streaming). |
| Copilot draait deterministisch zonder sleutel | test plus API | Klopt. Copilot loopt nu via de AI Gateway en valt zonder provider terug op het feitelijke antwoord. |
| Live handelen uit | `controls`, `test_api` | Klopt. |
| Command Center en HQ bouwen | `npm run lint`, `tsc`, `next build` | Klopt: 24 routes worden statisch gebouwd. |
| IWDA-strategieën blijven achter bij koop-en-houd | `research/RESULTS.md`, arena-records | Klopt; dit is niet opnieuw berekend. |
| Schone holdout vanaf 12-11-2026, minstens 63 dagen | `research/holdout/contamination.json` | Klopt en is niet aangeraakt. Er zijn geen holdout-evaluaties bijgekomen. |

## 2. Wat werkt echt

- **Paper trading van de holding-bots:** echte koersen (DELAYED), boekhouding, Risk Guardian, noodstop, journal. CONNECTED via de holding-database.
- **NEXUS-API:** 66 endpoints. Schrijvende endpoints vragen het admin-token en zijn rate-limited. TESTED.
- **Onderzoek:** lab, arena, holdout-bewaking, hypothesen en de leerlus. TESTED, op historische data.
- **Nieuw in 5.0:**
  - Provider Control Center met echte probes en foutclassificatie (IMPLEMENTED, TESTED; de probes zijn hier live uitgevoerd)
  - AI Gateway met routering, fallback, budget, stroomonderbreker en kostenlog (IMPLEMENTED, TESTED)
  - onafhankelijk debat (IMPLEMENTED, TESTED met opgenomen antwoorden)
  - AI Evaluation Arena (de vaste regels zijn gemeten; de modellen nog niet)
  - bewaking via `/api/ops/health`

## 3. Verbonden databronnen (gemeten op 13-11-2026 in deze ontwikkelomgeving)

| Bron | Status | Foutklasse | Netwerk zonder sleutel |
|---|---|---|---|
| Anthropic | NOT AVAILABLE | `credentials_missing` | bereikbaar (401 zonder sleutel) |
| Google Gemini | NOT AVAILABLE | `credentials_missing` | bereikbaar (403 zonder sleutel) |
| OpenAI | NOT AVAILABLE | `credentials_missing` | geblokkeerd door de proxy |
| xAI | NOT AVAILABLE | `credentials_missing` | geblokkeerd door de proxy |
| X API v2 | NOT AVAILABLE | `credentials_missing` | geblokkeerd door de proxy |
| GoPlus, DexScreener | NOT AVAILABLE | `network_blocked` | geen sleutel nodig |
| Fed, ECB, BLS, Kraken-status, Coinbase-status | NOT AVAILABLE | `network_blocked` | geen sleutel nodig |
| SEC-pers, EDGAR (AAPL, MSFT, NVDA) | NOT AVAILABLE | `credentials_missing` (contact-User-Agent) | geblokkeerd door de proxy |
| Yahoo, Bitvavo (direct) | NOT AVAILABLE hier | `network_blocked` | De holding haalt deze koersen al in GitHub Actions op; die data komt wél binnen via de paper-data-branch. |
| Holding-database (paper-data) | CONNECTED | n.v.t. | nieuwste dagkoers 1,5 dag oud |

**Conclusie:** het zijn geen storingen bij de aanbieders en geen verkeerde endpoints. Het gaat om twee dingen:
(a) de netwerkregels van deze ontwikkelomgeving, en (b) ontbrekende sleutels. Op een server met open uitgaand verkeer
plus de sleutels uit §5 werken dezelfde adapters zonder codewijziging. Dat is nog niet bewezen: de eerste echte run
moet het bevestigen.

## 4. Gesimuleerd of nog niet bewezen

- **OpenAI-, Gemini- en xAI-adapters:** alleen getest tegen opgenomen antwoordvormen (SIMULATED), nooit live aangeroepen.
- **Anthropic in de Council:** getest met nep-clients. Er is geen echte run in deze omgeving.
- **Nieuwsverwerking:** getest met een opgenomen RSS-voorbeeld (SIMULATED).
- **Demo-omgeving (`NEXUS_DEMO=1`):** volledig nep en zo gelabeld.
- **Meer modellen = beter:** NIET bewezen. Er is nog geen enkel model gemeten.

## 5. Ontbrekende gegevens en hoe je ze instelt (nooit via de frontend)

Zet deze waarden als omgevingsvariabelen op de server, of in de secret store van de host. Commit ze niet en plak ze
niet in de UI. De Provider Control Center toont alleen *welke namen* ontbreken.

| Variabele | Waarvoor | Hoe je hem krijgt |
|---|---|---|
| `ANTHROPIC_API_KEY` | Council, Copilot, debat | console.anthropic.com → API Keys |
| `OPENAI_API_KEY` + `NEXUS_OPENAI_MODEL` (+ `NEXUS_OPENAI_PRICE_IN/OUT`) | tweede mening (optioneel) | platform.openai.com → API keys; kies het model zelf. NEXUS gokt geen modelnamen. |
| `GEMINI_API_KEY` + `NEXUS_GEMINI_MODEL` (+ prijs) | tweede mening (optioneel) | aistudio.google.com → API key |
| `XAI_API_KEY` + `NEXUS_XAI_MODEL` (+ prijs) | optioneel | console.x.ai |
| `X_BEARER_TOKEN` | Social Radar | developer.x.com → Project → App → Keys and tokens → Bearer Token. Zoeken in recente posts (`/2/tweets/search/recent`) vraagt een betaald abonnement; met de gratis laag blijft de radar "NOT CONNECTED". |
| `NEXUS_SEC_USER_AGENT` | SEC/EDGAR | Eigen naam en e-mail, zoals de SEC vraagt (bijv. `JP-libau Holding research contact@…`) |
| `NEXUS_AI_DAILY_BUDGET_USD` | harde dagelijkse AI-limiet | standaard 3 |

**Netwerk (deployment-checklist):** sta uitgaand HTTPS toe naar:
- `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `api.x.ai`, `api.x.com`
- `api.gopluslabs.io`, `api.dexscreener.com`
- `www.federalreserve.gov`, `www.ecb.europa.eu`, `www.bls.gov`, `www.sec.gov`
- `status.kraken.com`, `status.coinbase.com`

Start daarna de API en klik in de Provider Control Center op "Alles nu testen". Elke bron hoort dan `Verbonden` te
tonen, of een foutklasse die zegt wat er mis is.

## 6. UI-routes

Er zijn 24 statisch gebouwde routes. 17 daarvan tonen echte data, waaronder de nieuwe `/operations` (Provider
Control Center). Drie terminals (crypto, stocks, forex) en Analytics & Reports zijn nog placeholders en staan als
zodanig gelabeld in de navigatie.

## 7. Agent-architectuur

AI Gateway → routeringsbeleid per taak → adapters (Anthropic SDK; OpenAI, Gemini en xAI via HTTP) → schema-controle
→ `ai_calls`-log. Verder:
- Council (bestaand, Anthropic) voor de rollen.
- Debat (onderzoeker en uitdager via de gateway; quant, risico en samenvatting in vaste code) → escalatie naar de CEO.
- NEXUS Central-takenmachine met 19 rollen.

Rekenwerk (waardering, boekhouding, risicolimieten, ordervalidatie, positiegrootte, statistiek, backtest, P&L) wordt
door de gateway geweigerd en blijft vaste code.

## 8. Testdekking

- NEXUS-backend: 156 tests, waarvan 23 nieuw in `test_ascension.py`.
- Holding-pakket: 138 tests.
- Web: lint, typecheck en build.
- Browser: Playwright-screenshots van alle hoofdpagina's (desktop, tablet, mobiel), zonder console-fouten.

Er zijn nog geen automatische visuele regressietests in CI; dat is mijlpaal D. Er is geen meting van de
testdekking in procenten.

## 9. Beveiligingsrisico's (eerlijk)

1. **Eén gedeeld admin-token, zonder gebruikers of rollen.** Het token staat alleen in het geheugen van het tabblad, maar er is geen MFA en geen scheiding tussen CEO en operator. Prioriteit voordat er meer gebruikers komen.
2. **Prompt-injectie via nieuws en sociale tekst.** Alle prompts markeren externe tekst als data. Verzonnen verwijzingen worden geweigerd en een taalmodel kan niets uitvoeren. Een model kan wel misleidende tekst teruggeven, maar dat leidt nooit tot een order of limietwijziging.
3. **Sleutels:** alleen omgevingsvariabelen. Ze worden uit foutmeldingen gefilterd (getest) en nooit opgeslagen of teruggegeven (getest).
4. **De rate limit zit in het geheugen per proces.** Bij meerdere instanties moet een gedeelde limiter komen.
5. **Auditlog met hash-keten:** wordt dagelijks gecontroleerd, en ook live via `/api/ops/health`.
6. **SQLite in ontwikkeling.** Voor productie is Postgres voorbereid (`psycopg`-extra), maar nog niet gedraaid.

## 10. Operationele afhankelijkheden

- GitHub Actions van de holding: koersen en paper-bots, met de `paper-data`-branch.
- Een server voor de NEXUS-API met uitgaand netwerk (§5).
- Een Next.js-host.
- Sleutels (§5).
- Tijd: 63 handelsdagen voor de schone holdout, minstens 8 nieuwsgebeurtenissen per categorie voor een event study, en minstens 30 afgerekende voorspellingen voor kalibratie.

## 11. Prestaties (lokaal, SQLite, echte paper-data)

| Endpoint | Tijd |
|---|---|
| `/api/command-center` (warme cache) | 6 ms |
| `/api/command-center` (koud) | 86 ms |
| `/api/pulse` | 66 ms |
| `/api/providers` | 12 ms |
| `/api/ai/gateway` | 4 ms |
| `/api/ops/health` | 74 ms (leest alle dagkoersen) |

Een volledige probe van 18 bronnen duurt ongeveer 4 s, omdat geblokkeerde hosts snel falen. De JS-chunks zijn
samen 1,1 MB ongecomprimeerd.

## 12. Eerste meting AI Evaluation Arena

Benchmark `news-labels-v1`: 30 handmatig gelabelde koppen, bevroren op 13-11-2026.

| Deelnemer | Nauwkeurigheid | Opmerking |
|---|---|---|
| Vaste regels vóór uitbreiding | 17/30 | Gemeten vóór de nieuwe categorieën. |
| Vaste regels na uitbreiding met 5 categorieën (macro, guidance, bedrijfsnieuws, beursstoringen, geopolitiek) | 28/30 (93%) | Te optimistisch: dezelfde ontwikkelaar schreef de set en de regels. |
| Taalmodellen | niet gemeten | Geen sleutels. |

De uitkomst zegt dus nog **niets** over de vraag of modellen of combinaties van modellen beter zijn.
