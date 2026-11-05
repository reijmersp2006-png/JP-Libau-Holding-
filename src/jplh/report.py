"""Backtest-rapport in Markdown: per afdeling wat werkte, vergeleken met koop-en-houd."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from jplh.backtest import WalkForwardResult
from jplh.models import Instrument

DESK_NAMES = {"crypto": "Crypto", "meme": "Memecoins", "stocks": "Aandelen", "metals": "Goud en zilver",
              "fx": "Valuta"}


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def backtest_report(results: list[WalkForwardResult], instruments: list[Instrument], interval: str,
                    train: int, test: int, now: datetime, demo: bool = False) -> str:
    cls_of = {i.symbol: i.asset_class.value for i in instruments}
    by_desk: dict[str, list[WalkForwardResult]] = defaultdict(list)
    for r in results:
        by_desk[cls_of[r.instrument]].append(r)

    lines = [f"# Backtest-lab JP-libau Holding, {now:%Y-%m-%d %H:%M} UTC", ""]
    if demo:
        lines += ["**Let op: NEP-DATA.** Deze uitslag zegt niets over echte markten.", ""]
    wins = sum(r.beats_benchmark for r in results)
    lines += [
        f"Walk-forward op {interval}-koersen: instellingen gekozen op {train} perioden, getest op de "
        f"volgende {test}. Alle cijfers hieronder zijn alleen van de geteste (ongeziene) perioden, "
        "na fee en slippage.",
        "",
        f"**{wins} van {len(results)}** combinaties van strategie en instrument deden het voor risico "
        "beter dan koop-en-houd (hogere Sharpe, geen diepere daling, minstens 5 trades).",
        "",
        "Lees dit voorzichtig: we testen veel combinaties, dus een paar winnaars kunnen puur geluk "
        "zijn. Alleen wat ook in de paper-fase blijft werken, telt.",
        "",
    ]
    for desk in ("crypto", "meme", "stocks", "metals", "fx"):
        rows = by_desk.get(desk)
        if not rows:
            continue
        lines += [f"## {DESK_NAMES[desk]}", "",
                  "| Instrument | Strategie | Rendement | Koop-en-houd | Sharpe | Sharpe K&H | Max daling | Max daling K&H | Trades | In markt | Oordeel |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
        for r in sorted(rows, key=lambda r: (r.instrument, -r.oos.sharpe)):
            verdict = "beter" if r.beats_benchmark else "niet beter"
            lines.append(
                f"| {r.instrument} | {r.family} | {_pct(r.oos.total_return)} | {_pct(r.benchmark.total_return)} | "
                f"{r.oos.sharpe:.2f} | {r.benchmark.sharpe:.2f} | {r.oos.max_drawdown * 100:.1f}% | "
                f"{r.benchmark.max_drawdown * 100:.1f}% | {r.oos.trades} | {r.oos.exposure * 100:.0f}% | {verdict} |")
        lines.append("")
    lines += ["## Gekozen instellingen per periode", ""]
    for r in results:
        chosen = ", ".join(f.chosen for f in r.folds)
        lines.append(f"- {r.instrument} / {r.family}: {chosen}")
    lines.append("")
    return "\n".join(lines)
