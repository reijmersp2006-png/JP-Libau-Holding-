export interface NavItem { href: string; label: string; phase: number; ready: boolean; group: string }

// ready = deze pagina toont al echte data. De rest laat eerlijk zien wat er nog moet komen.
export const NAV: NavItem[] = [
  { href: "/", label: "Command Center", phase: 1, ready: true, group: "Overzicht" },
  { href: "/hq", label: "AI Headquarters", phase: 3, ready: true, group: "Overzicht" },
  { href: "/decisions", label: "Decision Theater", phase: 6, ready: true, group: "Overzicht" },
  { href: "/research", label: "AI-onderzoek (Genesis)", phase: 7, ready: true, group: "Overzicht" },
  { href: "/news", label: "News Reactor", phase: 3, ready: true, group: "Intelligence" },
  { href: "/social", label: "Social Radar", phase: 3, ready: true, group: "Intelligence" },
  { href: "/pulse", label: "Global Market Pulse", phase: 6, ready: true, group: "Markten" },
  { href: "/crypto", label: "Crypto Workstation", phase: 6, ready: true, group: "Markten" },
  { href: "/stocks", label: "Equities Workstation", phase: 6, ready: true, group: "Markten" },
  { href: "/forex", label: "Forex Workstation", phase: 6, ready: true, group: "Markten" },
  { href: "/meme", label: "Meme Coin Research", phase: 6, ready: true, group: "Markten" },
  { href: "/radar", label: "Market Radar", phase: 2, ready: true, group: "Markten" },
  { href: "/strategy-lab", label: "Strategy Lab", phase: 4, ready: true, group: "Onderzoek" },
  { href: "/backtesting", label: "Backtesting Studio", phase: 4, ready: true, group: "Onderzoek" },
  { href: "/evolution", label: "Evolution Lab", phase: 4, ready: true, group: "Onderzoek" },
  { href: "/portfolio", label: "Portfolio Intelligence", phase: 1, ready: true, group: "Portefeuille" },
  { href: "/risk", label: "Risk Guardian", phase: 1, ready: true, group: "Portefeuille" },
  { href: "/execution", label: "Execution Monitor", phase: 5, ready: true, group: "Portefeuille" },
  { href: "/journal", label: "Trade Journal", phase: 1, ready: true, group: "Portefeuille" },
  { href: "/analytics", label: "Analytics & Reports", phase: 4, ready: false, group: "Systeem" },
  { href: "/operations", label: "Provider Control Center", phase: 5, ready: true, group: "Systeem" },
  { href: "/settings", label: "Settings & Integrations", phase: 1, ready: true, group: "Systeem" },
  { href: "/admin", label: "SaaS Administration", phase: 8, ready: true, group: "Systeem" },
];
