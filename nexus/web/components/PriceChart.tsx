"use client";

import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, createChart, createSeriesMarkers,
  type IChartApi, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { CHART } from "./ds";

export interface Bar { t: number; o: number; h: number; l: number; c: number; v: number }
export interface Overlay { key: string; color: string; values: (number | null)[] }
export interface Marker { t: number; text: string; simulated?: boolean }

/**
 * Grote koersgrafiek (TradingView Lightweight Charts): candles of lijn, volume, gemiddelden, RSI in een
 * eigen paneel, gebeurtenissen als markeringen en een optionele vergelijking (in % vanaf het eerste punt).
 * Alleen opgeslagen candles; er wordt niets doorgetrokken of bijgetekend.
 */
export function PriceChart({ bars, overlays = [], rsi, markers = [], compare, mode = "candles", height = 460, intraday = false }: {
  bars: Bar[]; overlays?: Overlay[]; rsi?: (number | null)[] | null; markers?: Marker[];
  compare?: { symbol: string; bars: Bar[] } | null; mode?: "candles" | "line"; height?: number; intraday?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current || bars.length < 2) return;
    const pct = !!compare;
    const chart = createChart(ref.current, {
      height, autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: CHART.text, fontSize: 11,
        fontFamily: "var(--font-geist-mono), monospace", panes: { separatorColor: CHART.gridStrong } },
      grid: { vertLines: { color: CHART.grid }, horzLines: { color: CHART.grid } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: CrosshairMode.Normal,
        vertLine: { color: CHART.crosshair, labelBackgroundColor: CHART.crosshairLabel },
        horzLine: { color: CHART.crosshair, labelBackgroundColor: CHART.crosshairLabel } },
      localization: { locale: "nl-NL", priceFormatter: (p: number) => pct ? `${p.toFixed(1)}%`
        : p.toLocaleString("nl-NL", { maximumFractionDigits: Math.abs(p) < 1 ? 6 : 2 }) },
    });
    chartRef.current = chart;
    const time = (t: number) => t as UTCTimestamp;
    const base = bars[0].c;
    const norm = (v: number, b: number) => (v / b - 1) * 100;

    let main;
    if (pct) {
      main = chart.addSeries(LineSeries, { color: CHART.metal, lineWidth: 2, priceLineVisible: false, title: "dit instrument" });
      main.setData(bars.map((b) => ({ time: time(b.t), value: norm(b.c, base) })));
      const cmp = compare!.bars.filter((b) => b.t >= bars[0].t);
      if (cmp.length > 1) {
        const s = chart.addSeries(LineSeries, { color: CHART.violet, lineWidth: 2, priceLineVisible: false, title: compare!.symbol });
        s.setData(cmp.map((b) => ({ time: time(b.t), value: norm(b.c, cmp[0].c) })));
      }
    } else if (mode === "line") {
      main = chart.addSeries(LineSeries, { color: CHART.metal, lineWidth: 2, priceLineVisible: false });
      main.setData(bars.map((b) => ({ time: time(b.t), value: b.c })));
    } else {
      main = chart.addSeries(CandlestickSeries, { upColor: CHART.up, downColor: CHART.down, borderVisible: false,
        wickUpColor: "rgba(76,196,149,.7)", wickDownColor: "rgba(226,90,100,.7)", priceLineVisible: false });
      main.setData(bars.map((b) => ({ time: time(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    }
    if (!pct) {
      for (const o of overlays) {
        const s = chart.addSeries(LineSeries, { color: o.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, title: o.key });
        s.setData(bars.flatMap((b, i) => (o.values[i] == null ? [] : [{ time: time(b.t), value: o.values[i] as number }])));
      }
    }
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    vol.setData(bars.map((b) => ({ time: time(b.t), value: b.v, color: b.c >= b.o ? "rgba(76,196,149,.22)" : "rgba(226,90,100,.22)" })));

    if (rsi && !pct) {
      const r = chart.addSeries(LineSeries, { color: CHART.ice, lineWidth: 1, priceLineVisible: false, title: "RSI 14",
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
      r.setData(bars.flatMap((b, i) => (rsi[i] == null ? [] : [{ time: time(b.t), value: rsi[i] as number }])));
      r.createPriceLine({ price: 70, color: "rgba(185,194,207,.25)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      r.createPriceLine({ price: 30, color: "rgba(185,194,207,.25)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      chart.panes()[0]?.setStretchFactor(3);
      chart.panes()[1]?.setStretchFactor(1);
    }
    const first = bars[0].t, last = bars[bars.length - 1].t;
    const ms = markers.filter((m) => m.t >= first && m.t <= last + 86400)
      .map((m) => {
        const nearest = bars.reduce((a, b) => (Math.abs(b.t - m.t) < Math.abs(a.t - m.t) ? b : a));
        return { time: time(nearest.t), position: "aboveBar" as const, shape: "circle" as const,
          color: m.simulated ? "#BEB4F0" : CHART.amber, text: m.simulated ? "sim" : "N", size: 0.6 };
      });
    if (ms.length) createSeriesMarkers(main, ms);
    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [bars, overlays, rsi, markers, compare, mode, height, intraday]);

  if (bars.length < 2) {
    return <div className="grid place-items-center text-[13px] text-slate-500" style={{ height }}>Geen opgeslagen candles voor deze tijdschaal.</div>;
  }
  return <div ref={ref} style={{ height }} className="w-full" role="img" aria-label="Koersgrafiek" />;
}
