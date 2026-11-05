"""Strategieën voor het backtest-lab.

Elke strategie zegt per koersperiode of ze in de markt wil zitten (1) of niet (0).
De beslissing voor periode i gebruikt ALLEEN data tot en met periode i; de backtest voert
hem pas uit bij de opening van periode i+1. Zo kan een strategie niet in de toekomst kijken.

Koop-en-houd is de maatlat: een strategie die daar na kosten en voor risico niet
overtuigend boven zit, voegt niets toe.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from jplh.models import Candle


def sma(values: list[float], n: int, i: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(values[i + 1 - n:i + 1]) / n


def rsi_series(closes: list[float], period: int) -> list[float | None]:
    """RSI met Wilder-gemiddelden."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


@dataclass(frozen=True)
class Strategy:
    name: str
    params: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if not self.params:
            return self.name
        return f"{self.name}(" + ", ".join(f"{k}={v}" for k, v in self.params.items()) + ")"

    @property
    def warmup(self) -> int:
        return 0

    def targets(self, candles: list[Candle]) -> list[int]:
        raise NotImplementedError

    def reason(self, candles: list[Candle]) -> str:
        """Korte uitleg van de laatste beslissing, voor het logboek."""
        t = self.targets(candles)
        return f"{self.label}: {'in de markt' if t and t[-1] else 'uit de markt'}"


class BuyHold(Strategy):
    def __init__(self) -> None:
        super().__init__("koop_en_houd")

    def targets(self, candles):
        return [1] * len(candles)


class TrendSMA(Strategy):
    """In de markt als het korte gemiddelde boven het lange ligt (met een kleine marge tegen heen-en-weer)."""

    def __init__(self, fast: int = 20, slow: int = 100, band: float = 0.01) -> None:
        super().__init__("trend", {"fast": fast, "slow": slow, "band": band})

    @property
    def warmup(self):
        return self.params["slow"]

    def targets(self, candles):
        p = self.params
        closes = [c.close for c in candles]
        out, state = [], 0
        for i in range(len(closes)):
            f, s = sma(closes, p["fast"], i), sma(closes, p["slow"], i)
            if f is not None and s is not None:
                if f > s * (1 + p["band"]):
                    state = 1
                elif f < s * (1 - p["band"]):
                    state = 0
            out.append(state if s is not None else 0)
        return out


class Momentum(Strategy):
    """In de markt als de koers hoger staat dan ``lookback`` perioden geleden (plus drempel)."""

    def __init__(self, lookback: int = 90, threshold: float = 0.0) -> None:
        super().__init__("momentum", {"lookback": lookback, "threshold": threshold})

    @property
    def warmup(self):
        return self.params["lookback"]

    def targets(self, candles):
        n, thr = self.params["lookback"], self.params["threshold"]
        closes = [c.close for c in candles]
        return [int(i >= n and closes[i] / closes[i - n] - 1 > thr) for i in range(len(closes))]


class Breakout(Strategy):
    """Donchian-uitbraak: kopen boven de hoogste koers van ``entry`` perioden, verkopen onder
    de laagste van ``exit`` perioden."""

    def __init__(self, entry: int = 55, exit: int = 20) -> None:
        super().__init__("uitbraak", {"entry": entry, "exit": exit})

    @property
    def warmup(self):
        return max(self.params["entry"], self.params["exit"])

    def targets(self, candles):
        e, x = self.params["entry"], self.params["exit"]
        out, state = [], 0
        for i, c in enumerate(candles):
            if i >= e and c.close > max(k.high for k in candles[i - e:i]):
                state = 1
            elif i >= x and c.close < min(k.low for k in candles[i - x:i]):
                state = 0
            out.append(state)
        return out


class MeanReversion(Strategy):
    """Terugkeer naar het gemiddelde: kopen als de RSI laag staat, verkopen als hij hoog staat."""

    def __init__(self, period: int = 14, low: float = 30, high: float = 55) -> None:
        super().__init__("terugkeer", {"period": period, "low": low, "high": high})

    @property
    def warmup(self):
        return self.params["period"] + 1

    def targets(self, candles):
        p = self.params
        rsi = rsi_series([c.close for c in candles], p["period"])
        out, state = [], 0
        for r in rsi:
            if r is not None:
                if r < p["low"]:
                    state = 1
                elif r > p["high"]:
                    state = 0
            out.append(state)
        return out


def _grid(cls, **choices) -> list[Strategy]:
    keys = list(choices)
    return [cls(**dict(zip(keys, combo))) for combo in itertools.product(*choices.values())]


# Bewust kleine roosters: hoe meer varianten je probeert, hoe groter de kans dat de
# "beste" alleen geluk had. Walk-forward test de keuze daarom altijd op nieuwe data.
FAMILIES: dict[str, list[Strategy]] = {
    "trend": [s for s in _grid(TrendSMA, fast=[10, 20, 50], slow=[50, 100, 200], band=[0.01])
              if s.params["fast"] < s.params["slow"]],
    "momentum": _grid(Momentum, lookback=[30, 90, 180], threshold=[0.0]),
    "uitbraak": _grid(Breakout, entry=[20, 55], exit=[10, 20]),
    "terugkeer": _grid(MeanReversion, period=[14], low=[25, 30], high=[50, 60]),
}
