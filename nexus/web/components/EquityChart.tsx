"use client";

import { AreaSeries, ColorType, LineSeries, LineStyle, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

/** Vermogenscurve met daaronder de daling vanaf de top (drawdown). Alleen echte punten uit de
 *  boekhouding; er wordt niets bijgetekend of doorgetrokken. */
export function EquityChart({ curve, capital, height = 300 }: { curve: [string, number][]; capital: number; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || curve.length < 2) return;
    const chart = createChart(ref.current, {
      height, autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#91A0B8", fontSize: 11,
        fontFamily: "var(--font-geist-mono), monospace", panes: { separatorColor: "rgba(148,163,184,.08)" } },
      grid: { vertLines: { color: "rgba(148,163,184,.04)" }, horzLines: { color: "rgba(148,163,184,.06)" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: "rgba(86,223,245,.35)", labelBackgroundColor: "#1f6f80" },
        horzLine: { color: "rgba(86,223,245,.35)", labelBackgroundColor: "#1f6f80" } },
      localization: { locale: "nl-NL", priceFormatter: (p: number) => p.toLocaleString("nl-NL", { maximumFractionDigits: 2 }) },
    });
    const seen = new Set<number>();
    const pts = curve
      .map(([t, v]) => ({ time: Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp, value: v }))
      .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)))
      .sort((a, b) => a.time - b.time);

    const up = pts[pts.length - 1].value >= capital;
    const eq = chart.addSeries(AreaSeries, {
      lineColor: up ? "#3ED6A3" : "#56DFF5", lineWidth: 2,
      topColor: up ? "rgba(62,214,163,.25)" : "rgba(86,223,245,.22)", bottomColor: "rgba(86,223,245,0)",
      priceLineVisible: false,
    });
    eq.setData(pts);
    const base = chart.addSeries(LineSeries, { color: "rgba(148,163,184,.45)", lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    base.setData(pts.map((p) => ({ time: p.time, value: capital })));

    let peak = capital;
    const dd = chart.addSeries(AreaSeries, { lineColor: "#FF627D", lineWidth: 1, topColor: "rgba(255,98,125,0)",
      bottomColor: "rgba(255,98,125,.28)", priceLineVisible: false,
      priceFormat: { type: "custom", formatter: (p: number) => `${p.toFixed(1)}%` } }, 1);
    dd.setData(pts.map((p) => { peak = Math.max(peak, p.value); return { time: p.time, value: (p.value / peak - 1) * 100 }; }));
    chart.panes()[1]?.setStretchFactor(0.28);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [curve, capital, height]);

  if (curve.length < 2) {
    return <div className="grid place-items-center text-sm text-slate-500" style={{ height }}>Nog te weinig meetpunten voor een curve.</div>;
  }
  return <div ref={ref} style={{ height }} className="w-full" />;
}

export function Spark({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return <svg className="h-6 w-20" />;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const d = values.map((v, i) => `${(i / (values.length - 1)) * 80},${22 - ((v - min) / span) * 20}`).join(" ");
  return (
    <svg viewBox="0 0 80 24" className="h-6 w-20" aria-hidden>
      <polyline points={d} fill="none" stroke={up ? "#3ED6A3" : "#FF627D"} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
