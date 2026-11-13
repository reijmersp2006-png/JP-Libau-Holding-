# GENESIS · Milestone E-rapport (E0 + E1)

Branch `claude/project-thread-gyycqq`, 13-11-2026. Gestopt na E1.7, zoals gevraagd. **Niet gemerged en niet uitgerold.**
De volgende milestone begint pas na expliciete goedkeuring van de founder.

**Kort**: de hele onderzoeksorganisatie (workflow, uitdager, consensus, ledger, evaluatie, CEO Control Center, AI HQ,
Decision Theater, Copilot) is gebouwd en getest (Gate 1). Operationeel (Gate 2) draait alles wat vaste code is op de
opgeslagen data. **Elke echte AI-aanroep en elk echt nieuwsbericht is BLOCKED**: er is geen sleutel en deze omgeving
weigert de feeds. Er is niets gesimuleerd om dat te verbergen. Eén commando (`nexus-genesis activate`) doet de echte
test zodra de sleutel in de data-feeds-omgeving staat. Gate 3 (meetbare waarde) is nog niet bereikt.

## 1. Gebouwde functionaliteit

| Onderdeel | Bestanden |
|---|---|
| AI Gateway-reparaties (model, max_tokens, prijs per model, kosten bij ongeldig antwoord, worst-case kostentoets, run-grens, pauze) | `ai_gateway.py`, `council.py` |
| Onderzoeksworkflow A/B/C/D via NEXUS Central, samenwerkingsprotocol, onafhankelijke uitdager, consensus met meningsverschillen | `genesis.py` |
| Audit van 19 rollen (vaste code en AI apart) | `agent_specs.py` |
| Prediction Ledger (append-only, hash-keten, amendementen, afrekenen, scores) | `ledger.py`, `db.py`, migratie `0006_genesis.py` |
| Evaluatie: uitdager-benchmark, vergelijking A–D, blinde CEO-beoordeling | `genesis_eval.py` |
| API met gescheiden onderzoeksrechten, daglimiet in de database | `genesis_api.py`, `app.py` |
| Activatiecommando `nexus-genesis` (readiness, activate met harde kostengrens) | `genesis_cli.py`, `pyproject.toml` |
| Copilot: de 7 nieuwe vragen uit records | `copilot.py` |
| Neural Core: overdrachten uit onderzoek, AI-lijnen, onderzoeksstatus, aanbiederfouten | `workstation.py`, `NeuralGraph.tsx` |
| CEO Control Center `/research` (opdrachten, ledger, evaluatie, kosten en storingen, gereedheid, pauze) | `web/app/research/page.tsx`, `nav.ts` |
| Decision Theater: onderzoekssporen per stap | `web/app/decisions/page.tsx` |
| Documentatie | 8 `docs/GENESIS-*.md` |

## 2. Tests

| Suite | Uitkomst |
|---|---|
| NEXUS-backend (pytest) | **205 geslaagd, 0 gefaald** (was 182; 23 nieuwe Genesis-tests) |
| Holding-onderzoek (pytest, `tests/`) | **138 geslaagd, 0 gefaald** |
| Web: tsc, eslint, `next build` | schoon, geslaagd (nieuwe route `/research`) |
| Visuele rooktest (`e2e/visual-smoke.mjs`, nu met `/research`) | geslaagd, geen consolefouten |
| Falende tests | **geen** |

Tijdens het testen gevonden en opgelost: (1) de Anthropic-adapter negeerde model en `max_tokens`; (2) een schema-ongeldig
antwoord werd als $0 gelogd; (3) een terugval op vaste code kon "hoog vertrouwen" tonen; (4) de rolaudit noemde rollen
met getest vaste-code-werk "BLOCKED" omdat hun AI-deel geblokkeerd was. Nu twee aparte statussen.

## 3. Verbonden aanbieders

| Aanbieder | Stand | Reden |
|---|---|---|
| Opgeslagen koersen (37 instrumenten t/m 11-11-2026) | CONNECTED (vertraagd) | lokaal opgeslagen |
| Anthropic | BLOCKED | geen sleutel; host bereikbaar (401) |
| OpenAI, Gemini, xAI | BLOCKED | geen sleutel; OpenAI en xAI ook door de proxy geweigerd |
| Fed, ECB, BLS, SEC, Kraken-, Coinbase-status | BLOCKED | proxy 403; SEC vraagt ook `NEXUS_SEC_USER_AGENT` |
| X API | BLOCKED | geen token, host geweigerd |
| GoPlus, DexScreener | BLOCKED | host geweigerd |

Bewijs: `nexus/research/genesis/readiness-20261113T162835Z.json` (alleen namen en statussen).

## 4. Echte AI-aanroepen

**0.** Geen sleutel. Geen enkele aanroep is nagebootst of als geslaagd gemeld.

## 5. Echte nieuwsgebeurtenissen

**0.** Feeds geweigerd door de omgeving. Fixtures worden nooit als echt geteld.

## 6. Echte overdrachten

Alleen vaste code: in de testdatabase leverden 16 onderzoeksopdrachten 128 overdrachten op tussen CIO, Regime, Technical,
Quant, Auditor, Risk en CEO (zichtbaar in de Neural Core). **Geen AI-overdrachten.**

## 7. Gesimuleerd

Niets in de Genesis-code. Tests gebruiken nep-adapters en nepdata; die zitten alleen in `tests/`. Het oude
fixture-spoor uit Milestone C blijft gemarkeerd als SIMULATED.

## 8. Geblokkeerd

E0.3 (eerste Council-taak en AI-stappen), E0.4 (echt nieuws), E0.5 (X, GoPlus, DexScreener), varianten B/C/D in de
vergelijking, AI-voorspellingen. Allemaal om dezelfde twee redenen: geen sleutel, en het netwerk van deze omgeving.

## 9. Onderzoeksresultaten

Variant A (vaste code) op de opgeslagen data, bijvoorbeeld BTC-EUR: geen aantoonbaar voordeel boven de historische
basiskans van 56% (95%-interval 54–59%) voor een hogere koers na 28 dagen (n = 1.475 overlappende vensters, data t/m 11-11-2026, vóór de holdout). Opvallend maar onbewezen: onder de 200-daagse lijn was dat 63% (n = 475), erboven 51% (n = 801); overlappende vensters maken de effectieve n kleiner. Aanbeveling
"volgen", vertrouwen "medium" volgens de regel. Dit is een beschrijving, geen strategie en geen advies.

## 10. Agent-evaluatie

- Uitdager (vaste controles): 11/11 geplante fouten gevonden, 0/3 vals alarm, **synthetische set**: toetst het
  mechaniek, niet echte modeluitvoer.
- Vergelijking A–D: A 3/3 klaar; B, C, D 0/3 (BLOCKED). **Nog geen uitspraak** over welke variant beter is.
- Ledger: 5 basislijn-voorspellingen geregistreerd in de testdatabase, 0 afgerekend (eerste horizon over 28 dagen).
- De 28/30 van de News Reactor geldt niet als bewijs van generalisatie.
- Zie `GENESIS-AGENT-EVALUATION.md`.

## 11. API-kosten

**$0,00** in deze milestone. Geschatte bovengrens voor de activatie: zie `GENESIS-ACTIVATION.md` (advies: eerst
`--max-usd 3`, de vergelijking A–D met 10 onderwerpen kost hoogstens ongeveer $8).

## 12. Beveiligingsbevindingen

Opgelost: gescheiden onderzoekstoken, pauze die niet aan handelen raakt, daglimiet in de database, prompt-injectie-test,
append-only ledger met databasetriggers. Open (hardingsplan in `GENESIS-SECURITY-REVIEW.md`): gedeeld admin-token,
rate limiting in het geheugen, SQLite, geen productie-authenticatie.

## 13. Screenshots

In de projectmap `nexus-ai/research/genesis/screenshots/`: `/research` (opdrachten, ledger, evaluatie, gereedheid) op
desktop, tablet en mobiel; Decision Theater; AI HQ met Neural Core en Copilot-antwoorden.

## 14. Resterende afhankelijkheden

1. `ANTHROPIC_API_KEY` in de omgeving "JP-Libau Holding NEXUS (data-feeds)" (door de CEO, nooit via chat).
2. `NEXUS_SEC_USER_AGENT`; optioneel `NEXUS_X_BEARER_TOKEN` en een tweede AI-sleutel voor een echt onafhankelijke uitdager.
3. Een nieuwe sessie op die omgeving om `nexus-genesis activate` te draaien.
4. Een budgetbesluit van de founder.
5. 28 dagen tijd voor de eerste afgerekende voorspellingen; daarna n ≥ 30 voor kalibratie.

## 15. Aanbevolen volgende stap

Nog **geen** nieuwe milestone. Eerst de activatie (E0.3 – E0.5) echt draaien met `--max-usd 3`, daarna de vergelijking
A–D met ongeveer $10 en de blinde beoordeling. Pas als variant C of D aantoonbaar beter is dan A en B, is er reden voor
meer agents. Het volledige Alpha Discovery Engine is bewust niet begonnen.

---

## Eisenlijst: alle 17 secties van MASTER PROMPT 7.0

| § | Eis | Stand | Waar |
|---|---|---|---|
| 1 | Repo, merge-staat en tests verifiëren; baseline-document | gedaan | `GENESIS-BASELINE.md` |
| 2 | Drie poorten en labels IMPLEMENTED / TESTED / CONNECTED / SIMULATED / BLOCKED / VALIDATED | gedaan, in elk document per onderdeel | alle docs, gereedheidsscherm |
| 3 | Anthropic: sleutel, auth, model, request, validatie, tokens, latency, fouten, kosten, budget, fallback, audit | TESTED; auth BLOCKED | `GENESIS-ACTIVATION.md` |
| 3 | Eerste echte Council-taak met tijdgestempelde bron en alle velden | gebouwd in `activate`; BLOCKED | `genesis_cli.py`, `activation.py` |
| 3 | Multi-model zonder duplicatie; zelfde model ≠ onafhankelijk | TESTED | `test_same_provider_challenge…` |
| 3 | Eerste operationeel spoor met exacte grens | gebouwd; grens nu bij `analysis` (geen aanbieder) | `activate` → `trace.boundary` |
| 4 | Echt nieuws via officiële feeds, pijplijn, tijdstempels, event-intelligence | TESTED; BLOCKED; nooit fixtures als echt | `news_step` in `genesis_cli.py` |
| 5 | X API-verificatie; GoPlus / DexScreener; ontbrekend = niet veilig; geen meme-uitvoering; social ≠ voorspellend | TESTED; BLOCKED | `GENESIS-ACTIVATION.md` |
| 6 | Audit van 19 rollen met alle tien velden | gedaan, getest | `GENESIS-AGENT-ARCHITECTURE.md` |
| 6 | Onderzoeksworkflow via Central, protocol, grenzen aan diepte, budget en tijd | TESTED | `GENESIS-COLLECTIVE-INTELLIGENCE.md` |
| 6 | Onafhankelijke uitdager (8 soorten) en meten of hij fouten vangt | TESTED, 11/11 synthetisch | idem |
| 6 | Consensus op bewijs, meningsverschillen bewaard | TESTED | idem |
| 7 | Tien maatstaven, bevroren basislijnen, onafhankelijke labels, lekpreventie, n en onzekerheid, A–D | gebouwd; meting B–D BLOCKED | `GENESIS-AGENT-EVALUATION.md` |
| 8 | Ledger met alle velden, onveranderbaar, amendementen, Brier, log loss, kalibratie, richting, t.o.v. basislijn | TESTED, CONNECTED voor basislijnen | `GENESIS-PREDICTION-LEDGER.md` |
| 9 | Gecontroleerd leren: onderzoek → voorspelling → waarneming → evaluatie → foutanalyse → voorstel → onafhankelijke validatie → menselijke goedkeuring → uitrol | onderzoek t/m foutanalyse gebouwd (workflow, ledger, afrekenen, scores, storingen); voorstel, validatie, goedkeuring en uitrol lopen via de bestaande Evolution Lab-, holdout- en CEO-regels; **niets wordt automatisch uitgerold** | `ledger.py`, `/api/genesis/failures`, CEO-takenwachtrij |
| 9 | Geheugensoorten gescheiden; agents wijzigen nooit code, rechten of limieten | onderzoeksrecords, voorspellingen, menselijke beoordelingen en audit zijn aparte tabellen; geen schrijfpad naar code of limieten | `db.py`, `GENESIS-SECURITY-REVIEW.md` |
| 10 | AI HQ hergebruikt bestaand ontwerp; Neural Core met taken, overdrachten, analyses, meningsverschillen, escalaties, aanbiederfouten, onderzoeksstatus | gedaan | `/hq`, screenshots |
| 10 | Decision Theater per stap: agent, model, bewijs, tijd, besluit, kosten, status | gedaan | `/decisions` |
| 10 | Copilot beantwoordt de 7 vragen uit echte records | gedaan, getest | `test_copilot_answers_genesis_questions_from_records` |
| 11 | CEO Control Center: aanvragen, status, bewijs, meningsverschillen, goedkeuren, pauzeren, kosten, mislukte taken, gereedheid | gedaan; goedkeuren via de bestaande takenwachtrij | `/research`, `/hq#taken` |
| 11 | Onderzoeksrechten los van handel; pauze raakt audit niet; geen AI keurt eigen rechten goed | TESTED | `GENESIS-SECURITY-REVIEW.md` |
| 12 | Gedeeld admin-token, rate limiting, SQLite, productie-auth; hardingsplan; prompt-injectietests | gedaan (plan + test) | idem |
| 13 | Holdout onaangeroerd; geen IWDA-claims; geen voorspellingen achteraf; onderzoek / paper / live gescheiden | nageleefd en getest (ledger weigert achteraf) | `GENESIS-PREDICTION-LEDGER.md` |
| 14 | Gebruik, tokens, kosten per taak en per bruikbare conclusie, mislukte aanroepen, retry-kosten, betrouwbaarheid; maximum vóór een betaalde test | gedaan | `/api/genesis/costs`, `GENESIS-ACTIVATION.md` |
| 15 | Roadmap E0.1 – E0.5, E1.1 – E1.7 | afgerond; E0.3 – E0.5 operationeel BLOCKED | dit rapport |
| 16 | Acht documenten en eindrapport met 15 punten | gedaan | `docs/GENESIS-*.md` |
| 17 | Stopvoorwaarden: alleen E0/E1, geen Alpha Discovery, geen live, geen SaaS-billing, niet mergen of uitrollen, geen abonnementen, holdout en risicocontroles intact | nageleefd | PR open, niet gemerged |
