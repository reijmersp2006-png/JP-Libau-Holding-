# GENESIS · Agent-architectuur (E1.1)

Er zijn **geen rollen bijgekomen**. De negentien bestaande rollen uit NEXUS Central zijn per rol vastgelegd in
`nexus/backend/nexus/agent_specs.py`. De status wordt **berekend uit wat er echt is gebeurd** (geslaagde AI-aanroepen,
workflowstappen), niet uit de configuratie. Elke rol heeft twee delen:

- **Vaste code**: berekeningen, regels en registers. TESTED betekent: unit tests slagen en het draait op opgeslagen data.
- **AI**: een gateway-taak of de Council. CONNECTED alleen na een echte geslaagde aanroep; IMPLEMENTED als een aanbieder
  is ingesteld maar nog niet gebruikt; BLOCKED als er geen aanbieder is.

De tabel hieronder is gegenereerd door `agent_specs.audit()` op 13-11-2026 in deze omgeving (geen sleutels). Live te zien
in `/research#gereedheid` en `GET /api/genesis/roles`.

| # | Rol | Soort | Verantwoordelijkheid | Gereedschap | Invoer → uitvoer | Bewijsregel | Aanbieder (taak) | Budget | Escalatie | Meting | Bij falen | Stap in workflow | Vaste code | AI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Founder / CEO | human | opdrachten geven, besluiten over vervolgonderzoek, kapitaal, limieten en live-poort | CEO Control Center, noodstop, pauze AI-onderzoek, takenwachtrij | conclusies, escalaties → besluit (goedkeuren/afwijzen) met notitie | ziet bij elk besluit het spoor en de bronnen | geen AI | stelt het dagbudget in | eindpunt van elke escalatie | doorlooptijd van besluiten | zonder besluit gebeurt er niets: escalaties blijven open | request | — | — |
| 2 | NEXUS Central (CIO) | coordinator | NEXUS Central: opdracht aannemen, kostenplan, rollen inschakelen, conclusie samenstellen | statusmachine, kostenplan, Prediction Ledger | onderzoeksvraag, uitkomsten van alle stappen → conclusie met hypothese, bewijs, tegenargumenten, vertrouwen, aanbeveling, meningsverschillen | neemt alleen beweringen over met geldige bron-ids zonder ernstige bezwaren | geen AI | weigert AI-stappen als het kostenplan niet in het resterende budget past | aanbeveling escalate_to_ceo wordt een CEO-taak | afgeronde opdrachten, kosten per bruikbare conclusie | workflow faalt zichtbaar (status failed) en bewaart wat er al was | intake, synthesis | TESTED | — |
| 3 | Quantitative Researcher | deterministic | meetbare hypothesen toetsen met vaste code | forward_stats, lab, champion | opgeslagen dagkoersen vóór de prospectieve holdout → basiskans, voorwaardelijke kansen, n, 95%-interval | elk getal herleidbaar tot opgeslagen candles | geen AI | geen AI | geen | juistheid (unit tests), gebruik van holdout-data = 0 | te weinig data: unavailable | quant | TESTED | — |
| 4 | Technical Analyst | llm | indicatoren en trend beschrijven | workstation-indicatoren | dagkoersen → trend, RSI, volatiliteit, drawdown, 52-weeks bereik | gemeten, met peilmoment | Council (Anthropic) | geen AI in de workflow (berekening is vaste code) | geen | juistheid | te weinig data: unavailable | technical | TESTED | BLOCKED |
| 5 | Fundamental Analyst | llm | brondocumenten lezen (8-K, persbericht); bij aandelen de analist | AI Gateway: financial_document, research_synthesis | opgeslagen documenten, feiten → bevindingen: bevestigd / speculatie / verwacht / nieuw, met ids | elke bevinding met document-id | anthropic, gemini, openai (`financial_document`) | valt onder het kostenplan van de opdracht | via de conclusie | onbewezen beweringen, rekenfouten, Brier van prob_up | geen document: not_applicable; geen aanbieder: blocked | fundamental, analysis (aandelen) | — | BLOCKED |
| 6 | Strategy Evolution Scientist | llm | strategie-experimenten in het Evolution Lab | Evolution Lab, holdout-register | onderzoeksresultaten → voorstellen voor experimenten | walk-forward na kosten | Council (Anthropic) | Council-budget | promotie alleen via CEO | experimenten met bewijs | geen promotie zonder bewijs | — | TESTED | BLOCKED |
| 7 | News Analyst | llm | nieuws valideren, ontdubbelen, classificeren, aan instrumenten koppelen | News Reactor, event-workflow | officiële feeds → gebeurtenis met herkomst en tijdstempels | bron-URL en publicatietijd | gemini, openai, anthropic (`news_classification`) | AI alleen voor classificatie naast vaste regels | hoge relevantie wordt een taak | juistheid labels op onafhankelijke set, latentie publicatie → detectie | feed onbereikbaar: unavailable, nooit een fixture als echt | (event-workflow) | TESTED | BLOCKED |
| 8 | Macro Economist | llm | analist voor metalen, valuta en context; macro-duiding | AI Gateway: research_synthesis | feiten → analyse volgens ANALYSIS_SCHEMA | ids en getallen met feit-id | anthropic, openai, gemini (`research_synthesis`) | kostenplan | via de conclusie | onbewezen beweringen, Brier | blocked zonder aanbieder | analysis (metalen, fx, context) | — | BLOCKED |
| 9 | Crypto Analyst | llm | analist voor crypto | AI Gateway: research_synthesis | feiten → analyse volgens ANALYSIS_SCHEMA | ids en getallen met feit-id | anthropic, openai, gemini (`research_synthesis`) | kostenplan | via de conclusie | onbewezen beweringen, Brier | blocked zonder aanbieder | analysis (crypto) | — | BLOCKED |
| 10 | Meme Coin Specialist | llm | analist voor memecoins, met verplichte veiligheidscontrole | AI Gateway, Social Radar | feiten, veiligheidscontrole → analyse | ontbrekende controle = niet veilig | anthropic, openai, gemini (`research_synthesis`) | kostenplan | via de conclusie | onbewezen beweringen, Brier | blocked zonder aanbieder; geen automatische uitvoering | analysis (meme) | — | BLOCKED |
| 11 | Social Intelligence Analyst | deterministic | X- en on-chainmetingen | X API, GoPlus, DexScreener | officiële API's → metingen met tijdstempel | bron en meettijd | geen AI | API-limieten | geen | dekking, versheid | niet verbonden: geen meting, geen schatting | — | TESTED | — |
| 12 | Execution Specialist | deterministic | paper-uitvoering | paper engine | goedgekeurde voorstellen → paper-vullingen | orderlog | geen AI | geen AI | fouten naar CEO | slippage tegen model | geen vulling | — | TESTED | — |
| 13 | Portfolio Manager | llm | portefeuille-oordeel in de Council | Council | posities → oordeel | posities en limieten | Council (Anthropic) | Council-budget | via Council | Brier | unavailable zonder sleutel | — | — | BLOCKED |
| 14 | Market Regime Specialist | llm | marktcontext en regime | Market Pulse (vaste code) | alle opgeslagen reeksen → regime, klassebewegingen | gemeten, met peilmoment | Council (Anthropic) | geen AI in de workflow | geen | juistheid | geen data: unavailable | market_context | TESTED | BLOCKED |
| 15 | Risk Guardian | deterministic | Risk Guardian: vaste limieten; in variant D ook een risicoreview in woorden | guardian, AI Gateway: risk_review (alleen tekst) | limieten, blootstelling, feiten → risico's en toegestane vervolgstap | limieten zijn code | anthropic, openai, gemini (`risk_review`) | geen AI behalve review in D | veto's zijn definitief | veto's, limietgebruik | bij twijfel: geen vervolg | risk, risk_review | TESTED | BLOCKED |
| 16 | Strategy Auditor | deterministic | onafhankelijke uitdager: vaste controles altijd, AI-uitdaging bij voorkeur bij een andere aanbieder | check_analysis, AI Gateway: independent_challenge | analyse, feiten → bevindingen per soort en ernst, bezwaren, alternatieve verklaringen | alleen feit-ids tellen; de analyse is geen bewijs | openai, gemini, xai, anthropic (`independent_challenge`) | kostenplan | ernstige bevindingen verlagen de aanbeveling | detectie van geplante fouten, herstel na herziening | zonder AI blijven de vaste controles werken | challenge_rules, challenge | TESTED | BLOCKED |
| 17 | Security & Compliance | deterministic | hash-keten, live-poort, toegang | auditlog, tokens | alle acties → auditregels | hash-keten | geen AI | geen AI | breuk in de keten naar CEO | ketencontrole ok | bij twijfel weigeren | (elke stap wordt geaudit) | TESTED | — |
| 18 | Model & Agent Evaluation | deterministic | Prediction Ledger en evaluatie van agents en varianten | ledger, genesis_eval | voorspellingen, uitkomsten, blinde beoordelingen → Brier, log loss, kalibratie, CI | onveranderbare voorspellingen | geen AI | geen AI | promotie alleen met bewijs en CEO | n per agent | te weinig n: geen uitspraak | ledger | TESTED | — |
| 19 | Experiment Tracking | deterministic | holdout-register en hypothesen | holdout, hypothesen | experimenten → registraties | manifest-hash | geen AI | geen AI | besmetting naar CEO | holdout onaangeroerd | besmet = geen oordeel | — | TESTED | — |

## Wat dit betekent

- **Niet goed**: geen enkele AI-rol is CONNECTED. Dat is de verwachte stand zolang er geen sleutel is. De vaste-code-delen
  (Quant, Technical, Regime, Risk Guardian, Auditor-controles, Ledger, Security) werken wel en zijn getest.
- De **onafhankelijke uitdager** is de bestaande Strategy Auditor: vaste controles altijd, AI-uitdaging bij voorkeur bij
  een andere aanbieder dan de auteur.
- Rollen zonder stap in de onderzoeksworkflow (Evolution, Social, Execution, Portfolio, Experiments) blijven bij hun
  bestaande werk. Ze krijgen geen schijnrol in Genesis.

## Grenzen die voor elke rol gelden

- Geen rol mag orders plaatsen, limieten of rechten wijzigen of productiecode aanpassen.
- AI-uitvoer is een mening en geen bewijs. Alleen feit-ids uit opgeslagen bronnen tellen als bewijs.
- Nieuws, social, web en modeluitvoer zijn onbetrouwbare invoer (zie `GENESIS-SECURITY-REVIEW.md`).
