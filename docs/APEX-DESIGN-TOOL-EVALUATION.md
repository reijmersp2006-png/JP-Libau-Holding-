# APEX · Evaluatie van ontwerpgereedschap

Beoordeeld op acht punten: ontwerpkwaliteit, compatibiliteit (Next.js 16, React 19, Tailwind 4, statische
prerender), prestaties, toegankelijkheid, licentie, kosten, onderhoud en meerwaarde voor NEXUS.
Er is niets gekocht en er zijn **geen nieuwe npm-pakketten** toegevoegd in Milestone D.

Schaal: ++ sterk, + goed, 0 neutraal, − zwak.

| Gereedschap | Kwaliteit | Compat. | Prestaties | Toegank. | Licentie | Kosten | Onderhoud | Meerwaarde | Besluit |
|---|---|---|---|---|---|---|---|---|---|
| **Figma** | ++ | n.v.t. (buiten de code) | n.v.t. | + (contrastplugins) | eigendom | gratis plan beperkt, teams betaald | + | 0 nu: één ontwikkelaar, tokens staan al in code | **niet nu**; zinvol zodra een tweede ontwerper meedoet |
| **21st.dev** | + (wisselend) | + (React/Tailwind) | wisselend | wisselend | per component verschillend | gratis; extra's betaald | − (losse kopieën) | − breekt de eenheid van één systeem | **nee**, hooguit als inspiratie |
| **shadcn/ui (Radix)** | ++ | ++ | + | ++ (Radix-primitieven) | MIT | gratis | + (code in de repo) | + voor complexe dialogen en een command-menu | **later, selectief**. Voor D waren eigen `Drawer`/`Tabs` met Esc, focus en aria genoeg, zonder nieuwe afhankelijkheid |
| **Motion** | ++ | ++ | + (~30–40 kB) | + (`useReducedMotion`) | MIT | gratis | ++ | 0: de benodigde beweging (binnenkomst, tick, opacity) is met CSS gedaan | **niet nodig**; CSS-transities met tokens volstaan en respecteren reduced motion |
| **GSAP** | ++ | + | ++ | 0 (zelf regelen) | eigen gratis licentie, niet open source | gratis | + | − overkill voor een data-dashboard | **nee** |
| **React Three Fiber** | ++ | + (alleen client) | − (three.js ~150 kB+, GPU) | − (3D is slecht toegankelijk) | MIT | gratis | + | − Neural Core is in SVG duidelijker, lichter en toegankelijk | **nee**; SVG-netwerk met lijstalternatief gebouwd |
| **TradingView Lightweight Charts** | ++ | ++ (v5, staat er al) | ++ (canvas; gemeten chunk 58 kB gzip) | 0 (canvas: tekstalternatief nodig, gebouwd) | Apache-2.0, attributie verplicht (logo blijft staan) | gratis | ++ | ++ koers, volume, RSI-paneel, markeringen | **ja, gebruikt** |
| **Apache ECharts** | ++ | + | 0 (~300 kB+ volledig, ~100 kB tree-shaken) | + (aria-module) | Apache-2.0 | gratis | ++ | 0: heatmap, correlatiematrix en staven zijn in ~150 regels SVG gedaan | **niet nu**; heroverwegen bij event studies of verdelingen |
| **Playwright** | n.v.t. | ++ (staat in de omgeving) | n.v.t. | + (rollen en labels in selectors) | Apache-2.0 | gratis | ++ | ++ | **ja, gebruikt**: screenshots, prestatiemeting, CI-rooktest |
| **Visual regression** (pixelvergelijking) | + | + | n.v.t. | n.v.t. | — | gratis (Playwright) of betaald (Chromatic, Percy) | − (baselines onderhouden) | 0 nu: koersen en tijdstempels veranderen per run, dus pixel-baselines geven vals alarm | **rooktest wel, pixeltest nog niet**; pas met een bevroren fixture-API |

## Waarom geen nieuwe pakketten

* De bundel blijft klein: de nieuwe `PriceChart` wordt pas geladen op de workstation-pagina's (`next/dynamic`, `ssr:false`). Lightweight Charts zelf werd al gebruikt voor de vermogens- en backtestgrafieken.
* Elk pakket is extra onderhoud en een extra leveranciersrisico. De opdracht vraagt geen aankopen.
* Alle doelen van D (toegankelijke drawer, tabs, beweging met reduced-motion, heatmap, correlatie) waren met de bestaande stack haalbaar.

## Wanneer dit herzien

| Aanleiding | Dan |
|---|---|
| Command-palette (⌘K) of complexe formulieren | shadcn/ui `Command` en `Dialog` toevoegen |
| Event studies, verdelingen, boxplots | ECharts (tree-shaken) alleen op de analysepagina's |
| Tweede ontwerper of externe review | Figma met dezelfde tokens |
| Stabiele fixture-API in CI | Playwright `toHaveScreenshot` met een drempel van ongeveer 0,1% |
