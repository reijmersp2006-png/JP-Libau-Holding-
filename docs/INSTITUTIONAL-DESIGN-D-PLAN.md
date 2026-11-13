# Plan voor Milestone D · institutioneel ontwerp (alleen plan, nog niet gebouwd)

> Milestone D begint pas na expliciete goedkeuring van de CEO. Dit document is een voorstel.

## Uitgangspunten

1. **Echte data eerst.** Elk scherm toont herkomst (CONNECTED, DELAYED, SIMULATED, ESTIMATE) en wordt leeg in
   plaats van mooi als er geen data is.
2. **Rust boven spektakel.** Animatie alleen om een verandering uit te leggen, nooit als decoratie. Respecteer
   `prefers-reduced-motion`.
3. **Eén ontwerpsysteem.** We bouwen verder op design 4.1 (Geist, donkere panelen, `Panel`, `StatusDot`,
   `TruthTag`), en niet op een tweede systeem ernaast.

## Gereedschap: beoordeling

| Gereedschap | Advies | Waarom |
|---|---|---|
| Figma | **ja, voor ontwerp** | schermen en tokens eerst vastleggen; de CEO kan meekijken zonder code |
| shadcn/ui (Radix) | **ja, selectief** | toegankelijke dialogen, tabs, tooltips en command-menu; de code staat in de repo, dus geen afhankelijkheid van een pakketversie; stijlen naar de 4.1-tokens |
| 21st.dev | nee als bron | handig als inspiratie, maar losse componenten met eigen stijl breken de eenheid |
| Motion (Framer Motion) | **ja, beperkt** | lay-out- en statusovergangen in React; klein en declaratief |
| GSAP | nee | krachtig voor tijdlijnen, maar overbodig naast Motion en met een eigen licentie |
| React Three Fiber | **alleen Neural Core, optioneel** | 3D is zwaar (bundel, GPU, toegankelijkheid). De huidige SVG-versie blijft de terugval |
| TradingView Lightweight Charts | **ja (staat er al, v5)** | koersgrafieken, candles, markeringen; snel en klein |
| Apache ECharts | **ja, voor analyses** | heatmaps, verdelingen, correlaties en event studies; niet voor koersgrafieken |
| Playwright | **ja** | staat in de omgeving; vaste schermroutes testen |
| Visual regression | **ja** | Playwright `toHaveScreenshot` met vaste data (fixture-API), drempel ≈ 0,1%; alleen op CI-Linux om fontverschillen te vermijden |

## Audit van de placeholders

| Route | Nu | Wat er al is | Wat ontbreekt voor een echt scherm |
|---|---|---|---|
| /crypto | Placeholder (fase 2) | Bitvavo-uur- en dagkoersen (DELAYED), papieren crypto-afdeling, alarmen | grafiek met indicatoren, markeringen voor orders en posities, funding en open interest (alleen lezen), on-chainstromen |
| /stocks | Placeholder (fase 2) | Yahoo-dagkoersen, IWDA-onderzoek (negatief t.o.v. kopen en vasthouden) | keuze van een aandelenbron (staat open, betaald), jaarcijfers en winstkalender |
| /forex | Placeholder (fase 2) | ECB-referentiekoersen, Yahoo FX | intraday-bron; zonder die bron is een "terminal" misleidend |
| /analytics | Placeholder | rapporten en evaluaties per afdeling | samengevoegd overzicht van prestaties en kosten |

Advies: bouw /crypto als eerste echte terminal (data is er al), en laat /stocks en /forex expliciet "bron nog niet
gekozen" tonen tot de CEO een bron kiest.

## Schermen

**Neural Core.** Het levende organogram van de 19 rollen. Knopen lichten op bij echte taken uit de wachtrij
(laatste 15 minuten); lijnen tonen overdrachten uit `event_workflows` en debatten. Geen nep-activiteit: stil is stil.
Klik op een knoop toont de laatste taken en kosten van die rol. Eerst SVG met Motion; R3F alleen als het meetbaar
iets toevoegt.

**Market Pulse.** Per activaklasse een rij met koers, 1d/7d, volatiliteit tegenover de eigen geschiedenis, regime en
versheid (een DELAYED-label is altijd zichtbaar). Heatmap in ECharts. Nieuws- en sociale signalen als kleine markers
op dezelfde tijdas.

**Decision Theater.** Eén besluit van begin tot eind: gebeurtenis → onderzoeker → uitdager (meningsverschillen naast
elkaar) → quant (cijfers uit vaste code) → Risk Guardian (welke regel) → CEO-knop. Gebouwd op `event_workflows`
en `debates`; elke bewering linkt naar haar bron, en beweringen zonder bewijs zijn grijs.

**Executive Command Center.** Het CEO-scherm: wat vraagt nu om een besluit, wat kostte AI vandaag, wat staat
uit en waarom (statussen uit het Provider Control Center), en de prestaties tegen de benchmark. Maximaal vijf
getallen boven de vouw.

**Trading Workstation.** Pas na de CEO-beslissing over live trading (nu UIT). Grafiek (Lightweight Charts), orderticket
dat alleen voorstellen maakt, Risk Guardian-uitleg naast elk ticket, en posities met P&L uit vaste code. Zonder
goedgekeurde gateway kan dit scherm niets uitvoeren.

## Volgorde en toetsing

1. Figma-ontwerp van Executive Command Center en Decision Theater (CEO beoordeelt).
2. Bouwen met shadcn/ui-primitieven en Motion; visual regression op vaste data.
3. /crypto-terminal met Lightweight Charts en ECharts.
4. Neural Core v2 en Market Pulse.
5. Trading Workstation alleen na een apart CEO-besluit.

Elke stap: lint, typecheck, build, Playwright-screenshots op desktop en mobiel, geen consolefouten, toegankelijkheid
(toetsenbord, contrast AA).
