// Visuele rooktest (Milestone D): elke hoofdpagina op desktop, tablet en mobiel.
// Faalt bij consolefouten of horizontale overloop; bewaart screenshots als CI-artefact.
// Geen pixelvergelijking: tijdstempels en koersen veranderen per run, dus pixel-baselines zouden vals alarm geven.
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = process.env.SMOKE_BASE ?? "http://127.0.0.1:3000";
const OUT = process.env.SMOKE_OUT ?? "smoke-shots";
const ROUTES = ["/", "/crypto", "/stocks", "/forex", "/meme", "/hq", "/decisions", "/news", "/social", "/pulse", "/evolution", "/operations", "/research"];
const VIEWPORTS = { desktop: [1440, 900], tablet: [834, 1112], mobile: [390, 844] };

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const problems = [], timing = [];
for (const [size, [width, height]] of Object.entries(VIEWPORTS)) {
  for (const route of ROUTES) {
    const page = await browser.newPage({ viewport: { width, height } });
    page.on("console", (m) => m.type() === "error" && problems.push(`${size} ${route} console: ${m.text()}`));
    page.on("pageerror", (e) => problems.push(`${size} ${route} pageerror: ${e.message}`));
    const t0 = Date.now();
    await page.goto(BASE + route, { waitUntil: "networkidle" });
    const loadMs = Date.now() - t0;
    await page.waitForTimeout(1000);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (overflow) problems.push(`${size} ${route}: horizontale overloop`);
    timing.push({ size, route, loadMs, overflow });
    await page.screenshot({ path: `${OUT}/${size}-${route === "/" ? "home" : route.slice(1)}.png`, fullPage: true });
    await page.close();
  }
}
await browser.close();
writeFileSync(`${OUT}/timing.json`, JSON.stringify(timing, null, 2));
console.log(timing.map((t) => `${t.size.padEnd(8)} ${t.route.padEnd(12)} ${t.loadMs} ms${t.overflow ? "  OVERLOOP" : ""}`).join("\n"));
if (problems.length) { console.error(problems.join("\n")); process.exit(1); }
