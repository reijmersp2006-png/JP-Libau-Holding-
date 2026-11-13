# Validatie van nieuws en sociaal (Milestone C3 en C4)

## Diagnose van de verbindingen (13 november 2026, echte probes)

| Bron | Status | Foutklasse | Oorzaak |
|---|---|---|---|
| Fed, ECB, BLS, Kraken-status, Coinbase-status | DISCONNECTED | network_blocked | de proxy van deze omgeving weigert de host |
| SEC-persberichten, EDGAR | NOT CONFIGURED | credentials_missing | `NEXUS_SEC_USER_AGENT` ontbreekt |
| X API v2 | NOT CONFIGURED | credentials_missing | `X_BEARER_TOKEN` ontbreekt |
| GoPlus, DexScreener | DISCONNECTED | network_blocked | proxy |
| Bitvavo, Yahoo | DISCONNECTED | network_blocked | proxy (de eerder opgehaalde dagkoersen zijn 2 dagen oud) |

## Nieuwsketen per bericht

Bron → ophalen → **tijdcontrole** (publicatie mag niet meer dan 5 minuten ná binnenkomst liggen, en niet ouder dan
30 dagen) → **ontdubbelen** (een duplicaat stopt hier) → instrumenten en feiten → classificatie → sociaal → markt
(5 dagen vooraf, dag erna; zonder vooruitkijken) → onderzoeker → uitdager → quant → risk → Central → uitleg → opslag.
URL, publicatietijd, binnenkomsttijd en de tijd van elke stap worden bewaard in het spoor (`event_workflows`).

Per gebeurtenis beantwoordt NEXUS: wat er gebeurde, welke instrumenten, of het bevestigd is (officiële bron en
feit), of het nieuw is, wat de markt verwachtte (zonder consensusbron: "niet beschikbaar"), of de markt al
reageerde, of er genoeg bewijs is voor onderzoek, en wat er ontbreekt.

### Event study: voorbereid, geen claims

Per categorie is een effect pas een kandidaat bij minstens 8 gemeten gebeurtenissen, met een betrouwbaarheidsinterval
dat nul uitsluit. Er zijn nu **nul** echte gebeurtenissen. Er wordt dus niets beweerd over welk soort nieuws de
koers beweegt.

## X en Meme Radar

| Onderdeel | Stand |
|---|---|
| Authenticatie | Bearer-token van de server; 401/403 worden uitgelegd |
| Zoeken | `tweets/search/recent`, zonder retweets, Engels |
| Paginering | via `next_token`, ingesteld maximum aantal pagina's |
| Rate limits | headers bewaard; stoppen als er minder dan 2 verzoeken over zijn; 429 wordt gemeld met resetmoment |
| Tijdstempels en ontdubbeling | `created_at` per post; ontdubbeld op post-id |
| Bewaren | alleen geaggregeerde metingen plus bronmetadata (pagina's, limiet, tijd), geen volledige posts |
| Narratief | vermeldingen per uur, unieke accounts, afwijking van de eigen basislijn (z-score vanaf 5 metingen), engagement, aandeel van het grootste account, gekopieerde tekst, nieuwe accounts, accounts met weinig volgers, botrisico, **contractadressen** (meerdere verschillende = waarschuwing voor nep-tokens), **momentum** (versnellend, stabiel, afnemend) |
| Betrouwbaarheid van influencers | alleen bij minstens 10 beoordeelde uitspraken; anders "te weinig" |
| On-chain veiligheid | GoPlus en DexScreener. Ontbrekende informatie telt nooit als veilig |
| Uitvoering | geen: de Meme Radar is alleen onderzoek |

Getest met opgenomen antwoorden: paginering, ontdubbeling, stoppen bij een lage limiet, geen verzoek zonder token,
contractadressen en momentum. Er zijn **geen echte X-metingen**.

## Wat nodig is voor echte validatie

1. Omgeving "data-feeds" (hosts toegestaan) plus `NEXUS_SEC_USER_AGENT`.
2. Twee tot vier weken echte nieuwsberichten verzamelen voordat er iets over koersreacties gezegd wordt.
3. X alleen na een CEO-besluit over een betaald plan.
