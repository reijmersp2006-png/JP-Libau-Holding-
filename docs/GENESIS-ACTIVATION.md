# GENESIS · Activatie (E0.2 – E0.5)

Stand 13-11-2026. Gate 1 (engineering) is voor de hele keten gehaald en getest. Gate 2 (operationeel) is in deze
ontwikkelsessie **BLOCKED**: er is geen AI-sleutel ingesteld en de omgeving weigert verbindingen naar nieuwsfeeds,
X, GoPlus en DexScreener (proxy 403 op CONNECT, zie `GENESIS-BASELINE.md`). Er is niets nagebootst om dat te verbergen.

## Wat in E0.2 is gerepareerd en getest (Anthropic eerst)

| Controle uit de opdracht | Stand | Bewijs |
|---|---|---|
| Sleutel laden | TESTED. Alleen server-side uit `ANTHROPIC_API_KEY` of `ANTHROPIC_AUTH_TOKEN`; nooit geprint, nooit naar de frontend | `ai_gateway.configured`, `/api/genesis/readiness` geeft alleen `usable` en een reden |
| Authenticatie | BLOCKED (geen sleutel). api.anthropic.com is bereikbaar: 401 zonder sleutel | baseline-hosttabel |
| Modelconfiguratie | **Gerepareerd**: de adapter negeerde `NEXUS_ANTHROPIC_MODEL` en `max_tokens`. Nu doorgegeven | `test_anthropic_adapter_honours_model_and_max_tokens` |
| Request-opbouw | TESTED: system-prompt, schema als gestructureerde uitvoer, server-side fallback (`fallbacks="default"`) | adapter-test |
| Antwoordvalidatie | TESTED: JSON-schema per taak; ongeldig = fout, nooit "half goed" | `test_invalid_answers_still_cost_money_and_run_cap_is_hard` |
| Tokens, latency, kosten | TESTED: per aanroep in `ai_calls`. **Gerepareerd**: een schema-ongeldig antwoord werd als $0 gelogd | idem |
| Prijzen | **Gerepareerd**: prijs volgt het ingestelde model (tabel per model, env-override); onbekend model = prijs onbekend = stap overgeslagen | `test_prices_follow_the_configured_model` |
| Budget | TESTED: dagbudget ($3 standaard) én harde grens per run; vóór elke aanroep wordt de slechtst denkbare prijs getoetst | `test_cost_plan_must_fit_the_budget_before_any_call` |
| Fallback | TESTED: volgende aanbieder in het beleid; zonder aanbieder BLOCKED + terugval op vaste code (gemarkeerd) | `test_without_provider_ai_steps_are_blocked_never_simulated` |
| Audit | TESTED: elke opdracht in de hash-keten (`research_workflow`) | auditlog |
| Pauze AI-onderzoek | **Nieuw**: aparte pauze, ook voor de Council; raakt handelen en audit niet | `test_pause_blocks_all_ai_but_not_deterministic_work` |

Multi-model: de gateway kent Anthropic, OpenAI, Gemini en xAI per taak. Dezelfde aanbieder twee keer telt **niet** als
onafhankelijk: de uitdager vraagt eerst een andere aanbieder en de conclusie zegt of dat lukte
(`test_same_provider_challenge_is_not_called_independent`). Er zijn geen dubbele aanroepen naar meerdere modellen voor
hetzelfde antwoord.

## Het activatiecommando

`nexus-genesis` (`nexus/backend/nexus/genesis_cli.py`) doet in één keer alles wat Gate 2 vraagt en schrijft het bewijs
naar `nexus/research/genesis/*.json`:

1. `readiness` (gratis): welke sleutels er zijn (alleen ja/nee) en een verbindingstest per bron.
2. `activate --max-usd X --confirm-budget X [--arms]`:
   - verbindingstest van alle bronnen;
   - officiële feeds ophalen (Fed, ECB, BLS, SEC, Kraken- en Coinbase-status), tot 3 echte gebeurtenissen door de
     event-workflow, met publicatie-, eerste-waarneming-, opname- en analysetijd, URL, id en status;
   - eerste echte Council-taak met tijdgestempelde bron (bron, aanbieder, model, rol, promptversie, tijden, tokens,
     kosten, gestructureerde uitvoer, bewijs, beperkingen);
   - één onderzoeksopdracht (variant C) en de spoorcontrole Request → Gateway → Specialist → Structured Analysis →
     Challenge → Risk → Research Record → Decision Theater → AI HQ → Copilot, met de **exacte grens** als een stap faalt;
   - met `--arms`: vergelijking A–D binnen wat er van de grens over is.

Zonder gelijke `--max-usd` en `--confirm-budget`, of boven $50, weigert het commando (exit 2, getest).

### Maximale kosten vooraf (alleen Anthropic, Opus-prijzen $4/$20 per MTok)

| Onderdeel | Bovengrens |
|---|---|
| Onderzoek variant B / C / D | $0,09 / $0,27 / $0,45 per opdracht |
| Event-workflow, 3 gebeurtenissen | ongeveer $0,80 |
| Eerste Council-taak | ongeveer $1 |
| Vergelijking A–D, 10 onderwerpen | ongeveer $8,10 |

Advies: eerst `--max-usd 3` zonder `--arms`; daarna, als dat goed ging, `--max-usd 10 --arms`. De grens is hard: de
gateway weigert elke aanroep waarvan de slechtst denkbare prijs er niet meer in past.

## Checklist voor de CEO (eenmalig)

1. Open in Claude de omgeving **"JP-Libau Holding NEXUS (data-feeds)"** (die laat de 14 benodigde hosts toe).
2. Zet daar als geheime variabele `ANTHROPIC_API_KEY`. Plak de sleutel nooit in een chat.
3. Zet `NEXUS_SEC_USER_AGENT` (bijvoorbeeld "JP-Libau Holding onderzoek contact@jouwdomein") voor SEC/EDGAR.
4. Optioneel: `NEXUS_X_BEARER_TOKEN` (officiële X API), `OPENAI_API_KEY` of `GEMINI_API_KEY` voor een echt
   onafhankelijke uitdager.
5. Start een **nieuwe** sessie op die omgeving (een lopende sessie ziet nieuwe sleutels niet) en laat draaien:
   `nexus-genesis readiness`, daarna `nexus-genesis activate --max-usd 3 --confirm-budget 3`.

## Stand per onderdeel

| Onderdeel | Gate 1 | Gate 2 | Reden |
|---|---|---|---|
| E0.3 Anthropic, eerste Council-taak | TESTED | BLOCKED | geen sleutel in deze omgeving |
| E0.3 Operationeel spoor | TESTED (zonder AI tot aan de grens) | BLOCKED vanaf `analysis` | zie `nexus/research/genesis/readiness-*.json` |
| E0.4 Echt nieuws | TESTED | BLOCKED | feeds geweigerd door de proxy; fixtures worden nooit als echt geteld |
| E0.5 X API | TESTED (auth, zoeken, paginering, rate limits, ontdubbeling in eerdere milestones) | BLOCKED | geen token, host geweigerd |
| E0.5 GoPlus / DexScreener | TESTED | BLOCKED | host geweigerd; ontbrekende controle = **niet veilig**; geen automatische meme-uitvoering |

Sociale signalen worden niet als voorspellend behandeld: er is geen meting die dat aantoont.
