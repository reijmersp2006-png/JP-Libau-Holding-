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
  nexus_paper?: { equity_eur: number; cash_eur: number; pnl_eur: number; label: DataLabel; starting_cash: number; positions: number; open_orders: number } | null;
}

export interface StrategySpec {
  key: string; version: number; name: string; family: string; params: Record<string, number>;
  required_data: string; entry: string; exit: string; sizing: string; risk: string; status: string;
}
export type Metrics = Partial<Record<"net_return" | "annual_return" | "max_drawdown" | "sharpe" | "sortino" | "win_rate" |
  "profit_factor" | "expectancy_eur" | "avg_win_eur" | "avg_loss_eur" | "exposure" | "costs_eur" | "costs_pct_capital" |
  "turnover" | "years", number | null>> & { trades?: number; sharpe_ci95?: [number, number] | null; periods?: number; liquidity_capped_orders?: number };
export interface BacktestResult {
  id: number; strategy: StrategySpec; symbol: string; asset_class: string; interval: string; data_label: DataLabel;
  data: { first: string; last: string; bars: number; warmup: number; oos_start: string };
  assumptions: { fee_pct: number; min_fee_eur: number; slippage_pct: number; spread_pct: number; execution: string; not_modeled: string[] };
  full: Metrics; in_sample: Metrics; out_of_sample: Metrics; benchmark: { full: Metrics; out_of_sample: Metrics };
  benchmark_relative_return: number;
  folds: { start: string; end: string; net_return: number; sharpe: number; max_drawdown: number; benchmark_return: number }[];
  regimes: Record<string, { periods: number; mean_return: number; benchmark_mean_return: number; sharpe: number }>;
  trades: { entry_ts: string; exit_ts: string | null; entry_price: number; exit_price: number | null; pnl_eur: number; ret: number; costs_eur: number; bars: number }[];
  equity: [string, number][]; benchmark_equity: [string, number][]; passes: boolean; verdict: string[];
}
export interface RunSummary {
  id: number; created_at: string; strategy: string; version: number; symbol: string; data_label: DataLabel; passes: boolean;
  verdict: string[]; oos: Metrics; benchmark_oos: Metrics;
}
export interface PaperOrder {
  id: number; client_order_id: string; proposal_id: number | null; symbol: string; side: string; notional_eur: number | null;
  quantity: number | null; filled_quantity: number; filled_notional_eur: number; status: string; reject_reason: string | null;
  created_at: string; updated_at: string;
}
export interface PaperExec { id: number; order_id: number; ts: string; symbol: string; side: string; quantity: number; price_eur: number; reference_price_eur: number; slippage_bps: number; fee_eur: number; data_label: DataLabel }
export interface PaperAccount {
  account_id: number; label: DataLabel; starting_cash: number; cash_eur: number; positions_value_eur: number; equity_eur: number;
  pnl_eur: number; realized_eur: number; unrealized_eur: number; fees_eur: number; drawdown: number; day_pnl_pct: number;
  positions: { symbol: string; asset_class: string; quantity: number; avg_price_eur: number; price_eur: number | null; price_label: DataLabel; value_eur: number; unrealized_eur: number | null }[];
  unpriced: string[]; equity_curve: [string, number][];
}
export interface PaperOverview { account: PaperAccount; orders: PaperOrder[]; executions: PaperExec[]; reconciliation: { ok: boolean; differences: string[]; checked_at: string }; live_enabled: boolean; settings: { participation: number; spread_pct: number } }
