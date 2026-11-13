# Provider Setup Guide

Alle sleutels staan **alleen als omgevingsvariabele op de server**. Nooit in de browser, nooit in git, nooit in de
database. De UI vraagt nooit om een sleutel en toont alleen de *namen* van ontbrekende variabelen. Na het instellen:
herstart de API en klik *Alles nu testen* op /operations. Een bron wordt pas groen (CONNECTED) na een echte,
geslaagde test.

Schaf niets automatisch aan. Elke betaalde dienst hieronder is een keuze van de CEO.

## AI-aanbieders

| Aanbieder | Verplicht | Optioneel | Host |
|---|---|---|---|
| Anthropic (standaard Council) | `ANTHROPIC_API_KEY` (of `ANTHROPIC_AUTH_TOKEN`) | `NEXUS_ANTHROPIC_MODEL`, `NEXUS_ANTHROPIC_MAX_CALLS_PER_DAY` | api.anthropic.com |
| OpenAI | `OPENAI_API_KEY`, `NEXUS_OPENAI_MODEL` | `NEXUS_OPENAI_PRICE_IN/OUT` (USD per mln tokens), `..._MAX_CALLS_PER_DAY` | api.openai.com |
| Google Gemini | `GEMINI_API_KEY`, `NEXUS_GEMINI_MODEL` | `NEXUS_GEMINI_PRICE_IN/OUT` | generativelanguage.googleapis.com |
| xAI | `XAI_API_KEY`, `NEXUS_XAI_MODEL` | `NEXUS_XAI_PRICE_IN/OUT` | api.x.ai |

- Voor andere aanbieders dan Anthropic wordt bewust **geen modelnaam gegokt**: zonder `NEXUS_*_MODEL` blijft de
  aanbieder uit.
- Zonder prijs worden kosten als "onbekend" getoond, niet als $0.
- Dagbudget voor alle AI samen: `NEXUS_AI_DAILY_BUDGET_USD` (standaard 3). Bij een leeg budget gaat er niets uit.
- AI-sporen voor nieuws per dag: `NEXUS_WORKFLOW_AI_PER_DAY` (standaard 5).

## Nieuws

| Bron | Nodig | Host |
|---|---|---|
| Federal Reserve, ECB, BLS | alleen netwerktoegang | www.federalreserve.gov, www.ecb.europa.eu, www.bls.gov |
| SEC-persberichten, EDGAR | `NEXUS_SEC_USER_AGENT` = "Naam contact@domein" (eis van de SEC) | www.sec.gov |
| Kraken- en Coinbase-status | alleen netwerktoegang | status.kraken.com, status.coinbase.com |

## Sociaal en on-chain

| Bron | Nodig | Host | Let op |
|---|---|---|---|
| X API v2 (zoeken) | `X_BEARER_TOKEN` | api.x.com | Zoeken vraagt een betaald plan. Bij 401/403 meldt NEXUS "token ongeldig of abonnement staat zoeken niet toe". Er worden alleen geaggregeerde metingen bewaard, geen posts. |
| GoPlus (tokenveiligheid) | netwerktoegang | api.gopluslabs.io | ontbrekende info = onveilig |
| DexScreener | netwerktoegang | api.dexscreener.com | alleen kijken, geen handelsbron |

## Marktdata

Bitvavo (crypto), Yahoo (aandelen, metalen, FX; onofficieel, niet voor commercieel gebruik) en ECB (FX) hebben geen
sleutel nodig, wel netwerktoegang. Dit zijn vertraagde dagkoersen (DELAYED).

## Rollen

| Variabele | Rol | Mag |
|---|---|---|
| `NEXUS_ADMIN_TOKEN` | CEO / admin | alles, inclusief modus, kill switch, activatietest, workflows en besluiten |
| `NEXUS_OPERATOR_TOKEN` | operator | bronnen testen, evaluatie draaien, koppen labelen |

## Foutklassen op /operations

| Klasse | Betekenis | Actie |
|---|---|---|
| credentials_missing | sleutel ontbreekt; er is niets verstuurd | variabele zetten |
| network_blocked | de proxy van de omgeving weigert de host | host toestaan in de netwerkinstellingen |
| network_unreachable / timeout | DNS, netwerk of traag | later opnieuw; bij herhaling de host controleren |
| auth_invalid (401) / auth_denied (403) | sleutel fout of zonder rechten | sleutel of abonnement controleren |
| rate_limited (429) | limiet bereikt | wachten; de stroomonderbreker gaat na 3 fouten in 15 min open |
| provider_outage (5xx) | storing bij de aanbieder | fallback naar de volgende aanbieder gebeurt automatisch |
| invalid_endpoint / parse_error | adres of antwoordformaat veranderd | code aanpassen |
