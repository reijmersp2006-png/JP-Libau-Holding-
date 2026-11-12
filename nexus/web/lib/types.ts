export type DataLabel = "LIVE" | "DELAYED" | "HISTORICAL" | "SIMULATED" | "UNAVAILABLE";

export interface GateCheck { check: string; passed: boolean; detail: string }
export interface KillStatus { engaged: boolean; nexus: boolean; holding_file: boolean; since: string | null; reason: string | null }
export interface Controls { mode: "research" | "paper" | "live"; kill: KillStatus; live_enabled: boolean; live_gate: GateCheck[] }

export interface Agent {
  id: string; n: number; name: string; status: "operational" | "partial" | "not_built"; phase: number;
  backed_by: string | null; covers: string[]; missing: string[]; last_activity: string | null; llm: boolean;
}
export interface Connection { name: string; kind: string; status: string; label: DataLabel; detail: string }
export interface Limit { key: string; label: string; value: number }
export interface RiskRow { key: string; label: string; used: number; limit: number; utilization: number; breached: boolean }

export interface Portfolio {
  label: DataLabel; as_of: string | null; equity_eur: number; capital_eur: number; cash_eur: number;
  pnl_eur: number; pnl_pct: number; realized_eur: number; unrealized_eur: number; buy_fees_eur: number;
  fees_eur: number; benchmark_eur: number | null; peak_eur: number; drawdown: number; day_pnl_pct: number;
  equity_curve: [string, number][]; days_active: number;
}
export interface Position {
  symbol: string; desk: string; quantity: number; avg_eur: number; price_eur: number | null; value_eur: number;
  unrealized_eur: number | null; pnl_pct: number | null; strategy: string; price_label: DataLabel; price_ts: string | null;
}
export interface Allocation { key: string; name: string; value_eur: number; pct: number }
export interface FeedItem { ts: string; desk: string; kind: string; text: string; detail: string; strategy?: string; level?: string; why?: string }
export interface Quote { symbol: string; name: string; desk: string; price: number | null; currency: string; change: number | null; fresh: boolean; line: number[]; label: DataLabel; ts: string | null }
export interface RadarRow { symbol: string; chain: string; price_usd: number; liquidity_usd: number; volume_24h_usd: number; change_24h_pct: number; flags: string[] }
export interface Proposal {
  id: number; created_at: string; source: string; symbol: string; asset_class: string; direction: string; strategy_id: string;
  status: string; executed: boolean; proposal: Record<string, unknown>;
  verdict: { approved: boolean; reason: string; checks: { rule: string; passed: boolean; detail: string }[] } | null;
}

export interface CommandCenter {
  generated_at: string; environment: "demo" | "paper" | "unconfigured"; available: boolean; as_of?: string;
  controls: Controls; agents: { summary: Record<string, number>; items: Agent[] }; connections: Connection[];
  proposals: Proposal[]; limits: Limit[]; portfolio: Portfolio | null; allocation: Allocation[]; positions: Position[];
  regime: { label: DataLabel; weather: { name: string; ok: boolean; text: string }[]; vix: number | null;
    risk_director: { vol: number; target: number; exposure: number; computed_at: string } | null } | null;
  findings: FeedItem[]; decisions: FeedItem[]; risk: RiskRow[]; market: Quote[]; radar: RadarRow[];
  health: { status: string; issues: { level: string; text: string }[] } | null; fills_today?: number;
}
