# Afhankelijkheden en externe API's

Geen enkele bron wordt als gratis of onbeperkt aangenomen. Status: wat nu gekoppeld is.

## Marktdata

| Bron | Voor | Toegang | Kosten / limieten | Status |
|---|---|---|---|---|
| Bitvavo publieke API | crypto, memecoins (EUR) | geen sleutel | gratis, rate-limit per IP | gekoppeld (uurkoersen → DELAYED) |
| Yahoo Finance chart-API | aandelen, ETF, goud/zilver, valuta | geen sleutel, onofficieel | kan zonder aankondiging haperen; niet voor commercieel gebruik | gekoppeld (DELAYED) |
| ECB Data Portal | officiële wisselkoersen | geen sleutel | gratis, dagelijks | gekoppeld |
| DexScreener | meme-radar (alleen kijken) | geen sleutel | gratis, ~300 req/min | gekoppeld |
| Bitvavo WebSocket | streaming crypto (LIVE) | geen sleutel voor ticker | gratis | fase 2 |
| Polygon.io / EODHD / FMP | officiële aandelenkoersen, fundamentals, winstkalender | API-sleutel | betaald (± $30–200/mnd) | fase 2, keuze nodig |
| FRED | macro (rente, inflatie, werkgelegenheid) | gratis sleutel | 120 req/min | fase 2 |
| Trading Economics | economische kalender | sleutel | betaald | fase 2, optioneel |
| Etherscan / Solscan / Birdeye | contract, houders, dev-wallets | sleutel | gratis tier met limieten | fase 2 |
| GoPlus / Honeypot.is | contractrechten, honeypot | (gratis) sleutel | limieten | fase 2 |
| Glassnode / CryptoQuant | on-chain, exchange-stromen | sleutel | betaald | later, optioneel |

## Uitvoering (fase 6, alleen na expliciete activatie)

| Broker | Markten | Opmerking |
|---|---|---|
| Bitvavo (trade-API) | crypto | sleutel zonder opnamerecht, IP-whitelist |
| Interactive Brokers / Saxo | aandelen, ETF, FX | beursuren, jurisdictie (NL), geen hefboom |
| DEX via wallet-signing | memecoins | nooit opgeslagen private keys |

## AI

| Bron | Voor | Status |
|---|---|---|
| Anthropic API | agents met gestructureerde output en tool calls | fase 3; `ANTHROPIC_API_KEY` alleen op de server |
| Provider-abstractie | model-agnostisch | fase 3 |

## Software

Backend: Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2, uvicorn; jplh (alleen standaardbibliotheek
+ certifi). Later: pandas, NumPy, SciPy, scikit-learn voor fase 4, Redis + worker voor taken, psycopg.
Frontend: Next.js 16, React 19, TypeScript, Tailwind 4, Lightweight Charts 5, Geist.
Infra: Docker, docker-compose (TimescaleDB), GitHub Actions (CI en de bestaande paper-ronde).
