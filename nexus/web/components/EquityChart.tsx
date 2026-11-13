"use client";

import { AreaSeries, ColorType, LineSeries, LineStyle, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

/** Vermogenscurve met daaronder de daling vanaf de top (drawdown). Alleen echte punten uit de
 *  boekhouding; er wordt niets bijgetekend of doorgetrokken. */
export function EquityChart({ curve, capital, height = 300, benchmark }: { curve: [string, number][]; capital: number; height?: number; benchmark?: [string, number][] | null }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || curve.length < 2) return;
    const chart = createChart(ref.current, {
      height, autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#8B94A3", fontSize: 11,
        fontFamily: "var(--font-geist-mono), monospace", panes: { separatorColor: "rgba(148,163,184,.08)" } },
      grid: { vertLines: { color: "rgba(148,163,184,.04)" }, horzLines: { color: "rgba(148,163,184,.06)" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: "rgba(185,194,207,.35)", labelBackgroundColor: "#232933" },
        horzLine: { color: "rgba(185,194,207,.35)", labelBackgroundColor: "#232933" } },
      localization: { locale: "nl-NL", priceFormatter: (p: number) => p.toLocaleString("nl-NL", { maximumFractionDigits: 2 }) },
    });
    const seen = new Set<number>();
    const pts = curve
      .map(([t, v]) => ({ time: Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp, value: v }))
      .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)))
      .sort((a, b) => a.time - b.time);

    const eq = chart.addSeries(AreaSeries, {
      lineColor: "#B9C2CF", lineWidth: 2, topColor: "rgba(185,194,207,.16)", bottomColor: "rgba(185,194,207,0)",
      priceLineVisible: false, title: "vermogen",
    });
    eq.setData(pts);
    const base = chart.addSeries(LineSeries, { color: "rgba(148,163,184,.45)", lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    base.setData(pts.map((p) => ({ time: p.time, value: capital })));
    if (benchmark && benchmark.length > 1) {
      const bs = new Set<number>();
      const bp = benchmark.map(([t, v]) => ({ time: Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp, value: v }))
        .filter((p) => (bs.has(p.time) ? false : (bs.add(p.time), true))).sort((a, b) => a.time - b.time);
      const b = chart.addSeries(LineSeries, { color: "#A79BEA", lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
        crosshairMarkerVisible: false, title: "koop-en-houd" });
      b.setData(bp);
    }

    let peak = capital;
    const dd = chart.addSeries(AreaSeries, { lineColor: "#E25A64", lineWidth: 1, topColor: "rgba(226,90,100,0)",
      bottomColor: "rgba(226,90,100,.22)", priceLineVisible: false,
      priceFormat: { type: "custom", formatter: (p: number) => `${p.toFixed(1)}%` } }, 1);
    dd.setData(pts.map((p) => { peak = Math.max(peak, p.value); return { time: p.time, value: (p.value / peak - 1) * 100 }; }));
    chart.panes()[1]?.setStretchFactor(0.28);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [curve, capital, height, benchmark]);

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
      <polyline points={d} fill="none" stroke={up ? "#4CC495" : "#E25A64"} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
