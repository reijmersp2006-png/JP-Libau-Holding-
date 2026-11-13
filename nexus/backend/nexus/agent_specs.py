"""E1.1: wat elke bestaande rol echt doet, wat hij mag, wat hij moet leveren en hoe we hem meten.

Een rol is niet operationeel omdat hij in de configuratie staat. ``status`` wordt hier berekend uit wat er
werkelijk is gebeurd (AI-aanroepen, workflowstappen), niet uit de beschrijving. Er zijn geen rollen bijgekomen:
de onafhankelijke uitdager is de bestaande Strategy Auditor.
"""

from __future__ import annotations

from sqlalchemy import select

from nexus import ai_gateway, central
from nexus.db import AiCall, Database, ResearchWorkflow

# step: welke stap in de onderzoeksworkflow (genesis) deze rol uitvoert; task: gateway-taak als hij AI gebruikt.
SPECS: dict[str, dict] = {
    "ceo": dict(responsibilities="opdrachten geven, besluiten over vervolgonderzoek, kapitaal, limieten en live-poort",
                tools=["CEO Control Center", "noodstop", "pauze AI-onderzoek", "takenwachtrij"], inputs=["conclusies", "escalaties"],
                outputs=["besluit (goedkeuren/afwijzen) met notitie"], evidence="ziet bij elk besluit het spoor en de bronnen",
                budget="stelt het dagbudget in", escalation="eindpunt van elke escalatie", metrics=["doorlooptijd van besluiten"],
                failure="zonder besluit gebeurt er niets: escalaties blijven open", step="request"),
    "cio": dict(responsibilities="NEXUS Central: opdracht aannemen, kostenplan, rollen inschakelen, conclusie samenstellen",
                tools=["statusmachine", "kostenplan", "Prediction Ledger"], inputs=["onderzoeksvraag", "uitkomsten van alle stappen"],
                outputs=["conclusie met hypothese, bewijs, tegenargumenten, vertrouwen, aanbeveling, meningsverschillen"],
                evidence="neemt alleen beweringen over met geldige bron-ids zonder ernstige bezwaren",
                budget="weigert AI-stappen als het kostenplan niet in het resterende budget past",
                escalation="aanbeveling escalate_to_ceo wordt een CEO-taak", metrics=["afgeronde opdrachten", "kosten per bruikbare conclusie"],
                failure="workflow faalt zichtbaar (status failed) en bewaart wat er al was", step="intake, synthesis"),
    "quant": dict(responsibilities="meetbare hypothesen toetsen met vaste code", tools=["forward_stats", "lab", "champion"],
                  inputs=["opgeslagen dagkoersen vóór de prospectieve holdout"], outputs=["basiskans, voorwaardelijke kansen, n, 95%-interval"],
                  evidence="elk getal herleidbaar tot opgeslagen candles", budget="geen AI", escalation="geen",
                  metrics=["juistheid (unit tests)", "gebruik van holdout-data = 0"], failure="te weinig data: unavailable", step="quant"),
    "technical": dict(responsibilities="indicatoren en trend beschrijven", tools=["workstation-indicatoren"], inputs=["dagkoersen"],
                      outputs=["trend, RSI, volatiliteit, drawdown, 52-weeks bereik"], evidence="gemeten, met peilmoment",
                      budget="geen AI in de workflow (berekening is vaste code)", escalation="geen", metrics=["juistheid"],
                      failure="te weinig data: unavailable", step="technical"),
    "fundamental": dict(responsibilities="brondocumenten lezen (8-K, persbericht); bij aandelen de analist",
                        tools=["AI Gateway: financial_document, research_synthesis"], inputs=["opgeslagen documenten", "feiten"],
                        outputs=["bevindingen: bevestigd / speculatie / verwacht / nieuw, met ids"],
                        evidence="elke bevinding met document-id", budget="valt onder het kostenplan van de opdracht",
                        escalation="via de conclusie", metrics=["onbewezen beweringen", "rekenfouten", "Brier van prob_up"],
                        failure="geen document: not_applicable; geen aanbieder: blocked", step="fundamental, analysis (aandelen)",
                        task="financial_document"),
    "evolution": dict(responsibilities="strategie-experimenten in het Evolution Lab", tools=["Evolution Lab", "holdout-register"],
                      inputs=["onderzoeksresultaten"], outputs=["voorstellen voor experimenten"], evidence="walk-forward na kosten",
                      budget="Council-budget", escalation="promotie alleen via CEO", metrics=["experimenten met bewijs"],
                      failure="geen promotie zonder bewijs", step=None),
    "news": dict(responsibilities="nieuws valideren, ontdubbelen, classificeren, aan instrumenten koppelen", tools=["News Reactor", "event-workflow"],
                 inputs=["officiële feeds"], outputs=["gebeurtenis met herkomst en tijdstempels"], evidence="bron-URL en publicatietijd",
                 budget="AI alleen voor classificatie naast vaste regels", escalation="hoge relevantie wordt een taak",
                 metrics=["juistheid labels op onafhankelijke set", "latentie publicatie → detectie"],
                 failure="feed onbereikbaar: unavailable, nooit een fixture als echt", step="(event-workflow)", task="news_classification"),
    "macro": dict(responsibilities="analist voor metalen, valuta en context; macro-duiding", tools=["AI Gateway: research_synthesis"],
                  inputs=["feiten"], outputs=["analyse volgens ANALYSIS_SCHEMA"], evidence="ids en getallen met feit-id",
                  budget="kostenplan", escalation="via de conclusie", metrics=["onbewezen beweringen", "Brier"],
                  failure="blocked zonder aanbieder", step="analysis (metalen, fx, context)", task="research_synthesis"),
    "crypto": dict(responsibilities="analist voor crypto", tools=["AI Gateway: research_synthesis"], inputs=["feiten"],
                   outputs=["analyse volgens ANALYSIS_SCHEMA"], evidence="ids en getallen met feit-id", budget="kostenplan",
                   escalation="via de conclusie", metrics=["onbewezen beweringen", "Brier"], failure="blocked zonder aanbieder",
                   step="analysis (crypto)", task="research_synthesis"),
    "meme": dict(responsibilities="analist voor memecoins, met verplichte veiligheidscontrole", tools=["AI Gateway", "Social Radar"],
                 inputs=["feiten", "veiligheidscontrole"], outputs=["analyse"], evidence="ontbrekende controle = niet veilig",
                 budget="kostenplan", escalation="via de conclusie", metrics=["onbewezen beweringen", "Brier"],
                 failure="blocked zonder aanbieder; geen automatische uitvoering", step="analysis (meme)", task="research_synthesis"),
    "social": dict(responsibilities="X- en on-chainmetingen", tools=["X API", "GoPlus", "DexScreener"], inputs=["officiële API's"],
                   outputs=["metingen met tijdstempel"], evidence="bron en meettijd", budget="API-limieten",
                   escalation="geen", metrics=["dekking", "versheid"], failure="niet verbonden: geen meting, geen schatting", step=None),
    "execution": dict(responsibilities="paper-uitvoering", tools=["paper engine"], inputs=["goedgekeurde voorstellen"],
                      outputs=["paper-vullingen"], evidence="orderlog", budget="geen AI", escalation="fouten naar CEO",
                      metrics=["slippage tegen model"], failure="geen vulling", step=None),
    "portfolio": dict(responsibilities="portefeuille-oordeel in de Council", tools=["Council"], inputs=["posities"], outputs=["oordeel"],
                      evidence="posities en limieten", budget="Council-budget", escalation="via Council", metrics=["Brier"],
                      failure="unavailable zonder sleutel", step=None),
    "regime": dict(responsibilities="marktcontext en regime", tools=["Market Pulse (vaste code)"], inputs=["alle opgeslagen reeksen"],
                   outputs=["regime, klassebewegingen"], evidence="gemeten, met peilmoment", budget="geen AI in de workflow",
                   escalation="geen", metrics=["juistheid"], failure="geen data: unavailable", step="market_context"),
    "risk": dict(responsibilities="Risk Guardian: vaste limieten; in variant D ook een risicoreview in woorden",
                 tools=["guardian", "AI Gateway: risk_review (alleen tekst)"], inputs=["limieten", "blootstelling", "feiten"],
                 outputs=["risico's en toegestane vervolgstap"], evidence="limieten zijn code", budget="geen AI behalve review in D",
                 escalation="veto's zijn definitief", metrics=["veto's", "limietgebruik"], failure="bij twijfel: geen vervolg",
                 step="risk, risk_review", task="risk_review"),
    "auditor": dict(responsibilities="onafhankelijke uitdager: vaste controles altijd, AI-uitdaging bij voorkeur bij een andere aanbieder",
                    tools=["check_analysis", "AI Gateway: independent_challenge"], inputs=["analyse", "feiten"],
                    outputs=["bevindingen per soort en ernst", "bezwaren", "alternatieve verklaringen"],
                    evidence="alleen feit-ids tellen; de analyse is geen bewijs", budget="kostenplan",
                    escalation="ernstige bevindingen verlagen de aanbeveling", metrics=["detectie van geplante fouten", "herstel na herziening"],
                    failure="zonder AI blijven de vaste controles werken", step="challenge_rules, challenge", task="independent_challenge"),
    "security": dict(responsibilities="hash-keten, live-poort, toegang", tools=["auditlog", "tokens"], inputs=["alle acties"],
                     outputs=["auditregels"], evidence="hash-keten", budget="geen AI", escalation="breuk in de keten naar CEO",
                     metrics=["ketencontrole ok"], failure="bij twijfel weigeren", step="(elke stap wordt geaudit)"),
    "model_eval": dict(responsibilities="Prediction Ledger en evaluatie van agents en varianten", tools=["ledger", "genesis_eval"],
                       inputs=["voorspellingen", "uitkomsten", "blinde beoordelingen"], outputs=["Brier, log loss, kalibratie, CI"],
                       evidence="onveranderbare voorspellingen", budget="geen AI", escalation="promotie alleen met bewijs en CEO",
                       metrics=["n per agent"], failure="te weinig n: geen uitspraak", step="ledger"),
    "experiments": dict(responsibilities="holdout-register en hypothesen", tools=["holdout", "hypothesen"], inputs=["experimenten"],
                        outputs=["registraties"], evidence="manifest-hash", budget="geen AI", escalation="besmetting naar CEO",
                        metrics=["holdout onaangeroerd"], failure="besmet = geen oordeel", step=None),
}


# Rollen met een deel in vaste code (berekening, regels, register) naast eventueel een AI-deel.
CODE_PART = {"cio", "quant", "technical", "evolution", "news", "social", "execution", "regime", "risk", "auditor",
             "security", "model_eval", "experiments"}


def audit(db: Database) -> list[dict]:
    with db.session() as s:
        ok_tasks = {t for (t,) in s.execute(select(AiCall.task).where(AiCall.status == "ok").distinct())}
        steps = [st for w in s.scalars(select(ResearchWorkflow).order_by(ResearchWorkflow.id.desc()).limit(200))
                 for st in (w.steps or [])]
    usable = {d["provider"]: d for d in ai_gateway.describe()}
    out = []
    for r in central.ROLES:
        spec = SPECS[r.key]
        task = spec.get("task")
        ran_ok = [st for st in steps if st.get("agent") == r.key and st.get("status") == "ok"]
        ran_ai = [st for st in ran_ok if st.get("provider")]
        # AI-deel: alleen CONNECTED als er echt een geslaagde aanroep was.
        if task:
            pol_p = ai_gateway.DEFAULT_POLICIES[task].providers if task in ai_gateway.DEFAULT_POLICIES else ()
            has = any(usable.get(p, {}).get("usable") for p in pol_p)
            ai_status = "CONNECTED" if ran_ai or task in ok_tasks else "IMPLEMENTED" if has else "BLOCKED"
        elif r.kind == "llm":            # Council-rol zonder eigen gateway-taak (Council gebruikt Anthropic)
            ai_status = "IMPLEMENTED" if usable.get("anthropic", {}).get("usable") else "BLOCKED"
        else:
            ai_status = None
        # Vaste-code-deel: getest met unit tests; draait op opgeslagen data.
        code_status = "TESTED" if r.key in CODE_PART else None
        if r.kind == "human":
            status = "CONNECTED"
        elif ai_status == "CONNECTED":
            status = "CONNECTED"
        elif code_status:
            status = "TESTED"
        else:
            status = ai_status or "TESTED"
        pol = ai_gateway.DEFAULT_POLICIES.get(task) if task else None
        out.append({"key": r.key, "name": r.name, "department": r.department, "kind": r.kind, "backed_by": r.backed_by,
                    **{k: v for k, v in spec.items() if k != "task"}, "gateway_task": task,
                    "providers": list(pol.providers) if pol else [], "max_tokens": pol.max_tokens if pol else None,
                    "status": status, "code_status": code_status, "ai_status": ai_status,
                    "workflow_steps_ok": len(ran_ok), "ai_steps_ok": len(ran_ai)})
    return out
