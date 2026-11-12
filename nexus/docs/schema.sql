-- NEXUS AI · doel-schema voor PostgreSQL 16 + TimescaleDB.
-- Fase 1 gebruikt de tabellen gemarkeerd met [F1] (via SQLAlchemy, ook op SQLite).
-- De rest is het ontwerp voor fase 2-6. Alle tijden in UTC (timestamptz).

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Referentie ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE accounts (                         -- paper, broker- of exchange-account
  id            bigserial PRIMARY KEY,
  name          text NOT NULL,
  kind          text NOT NULL CHECK (kind IN ('paper','broker','exchange','wallet')),
  provider      text NOT NULL,                  -- 'jplh-paper', 'bitvavo', 'ibkr', ...
  is_live       boolean NOT NULL DEFAULT false, -- alleen true na live-poort + activatie
  permissions   jsonb NOT NULL DEFAULT '{}',    -- gecontroleerd: nooit 'withdraw'
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE instruments (
  id            bigserial PRIMARY KEY,
  symbol        text NOT NULL,
  asset_class   text NOT NULL CHECK (asset_class IN ('crypto','meme','stocks','etf','metals','fx')),
  venue         text NOT NULL,
  currency      char(3) NOT NULL,
  chain         text,                           -- voor tokens
  contract      text,
  active_from   date, active_to date,           -- survivorship: ook verdwenen instrumenten blijven
  UNIQUE (symbol, venue)
);

CREATE TABLE data_sources (
  id            text PRIMARY KEY,               -- 'bitvavo', 'yahoo', 'ecb', 'dexscreener', ...
  kind          text NOT NULL,                  -- marketdata | fundamentals | onchain | news | broker | ai
  licence       text,                           -- gebruiksvoorwaarden / betaald plan
  streaming     boolean NOT NULL DEFAULT false
);

-- ── Marktdata (hypertables) ────────────────────────────────────────────────────────────────
CREATE TABLE candles (
  instrument_id bigint NOT NULL REFERENCES instruments(id),
  interval      text NOT NULL,
  ts            timestamptz NOT NULL,           -- begin van de periode
  open numeric NOT NULL, high numeric NOT NULL, low numeric NOT NULL, close numeric NOT NULL,
  volume        numeric NOT NULL DEFAULT 0,
  source_id     text NOT NULL REFERENCES data_sources(id),
  fetched_at    timestamptz NOT NULL,           -- point-in-time: wat wisten we wanneer
  PRIMARY KEY (instrument_id, interval, ts)
);
SELECT create_hypertable('candles', 'ts', if_not_exists => true);

CREATE TABLE quotes (                           -- bid/ask voor spread- en slippage-modellen
  instrument_id bigint NOT NULL REFERENCES instruments(id),
  ts timestamptz NOT NULL, bid numeric, ask numeric, bid_size numeric, ask_size numeric,
  source_id text NOT NULL REFERENCES data_sources(id)
);
SELECT create_hypertable('quotes', 'ts', if_not_exists => true);

CREATE TABLE corporate_actions (
  instrument_id bigint NOT NULL REFERENCES instruments(id),
  ex_date date NOT NULL, kind text NOT NULL CHECK (kind IN ('split','dividend','delisting','merger')),
  ratio numeric, amount numeric, known_at timestamptz NOT NULL,
  PRIMARY KEY (instrument_id, ex_date, kind)
);

CREATE TABLE token_security (                   -- meme-checks; verplicht vóór elke koop
  instrument_id bigint NOT NULL REFERENCES instruments(id),
  checked_at timestamptz NOT NULL,
  verified_contract boolean, honeypot boolean, sell_tax_pct numeric, owner_can_mint boolean,
  liquidity_locked boolean, top10_holder_pct numeric, dev_wallet_pct numeric, liquidity_usd numeric,
  flags jsonb NOT NULL DEFAULT '[]', passed boolean NOT NULL,
  PRIMARY KEY (instrument_id, checked_at)
);

-- ── Besturing en audit ─────────────────────────────────────────────────────────────────────
CREATE TABLE system_state (                     -- [F1] modus, noodstop
  key text PRIMARY KEY, value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (                        -- [F1] alleen toevoegen
  id bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL, action text NOT NULL, detail jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON audit_log (ts DESC);
CREATE INDEX ON audit_log (action);
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- ── Strategieën en onderzoek ───────────────────────────────────────────────────────────────
CREATE TABLE strategies (
  id text PRIMARY KEY, family text NOT NULL,      -- trend, momentum, mean_reversion, breakout, ...
  description text
);
CREATE TABLE strategy_versions (
  strategy_id text NOT NULL REFERENCES strategies(id), version int NOT NULL,
  params jsonb NOT NULL, code_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'research' CHECK (status IN ('research','paper','live_candidate','retired')),
  PRIMARY KEY (strategy_id, version)
);
CREATE TABLE backtest_runs (
  id bigserial PRIMARY KEY, strategy_id text NOT NULL, version int NOT NULL,
  universe jsonb NOT NULL, start_ts timestamptz NOT NULL, end_ts timestamptz NOT NULL,
  method text NOT NULL,                           -- walk_forward | out_of_sample | monte_carlo
  cost_model jsonb NOT NULL, metrics jsonb NOT NULL,   -- incl. betrouwbaarheidsintervallen
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (strategy_id, version) REFERENCES strategy_versions
);

-- ── AI Expert Council ──────────────────────────────────────────────────────────────────────
CREATE TABLE agent_runs (
  id bigserial PRIMARY KEY, agent_id text NOT NULL, started_at timestamptz NOT NULL,
  finished_at timestamptz, status text NOT NULL, model text, provider text,
  input_hash text NOT NULL, inputs jsonb NOT NULL, output jsonb, error text,
  tokens_in int, tokens_out int
);
CREATE TABLE agent_findings (                   -- elke bewering met bewijs
  id bigserial PRIMARY KEY, run_id bigint NOT NULL REFERENCES agent_runs(id),
  claim text NOT NULL, stance text CHECK (stance IN ('for','against','neutral')),
  evidence jsonb NOT NULL, data_labels text[] NOT NULL
);

-- ── Voorstellen, risico, orders ────────────────────────────────────────────────────────────
CREATE TABLE trade_proposals (                  -- [F1]
  id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
  idempotency_key text NOT NULL UNIQUE, source text NOT NULL,
  asset_class text NOT NULL, symbol text NOT NULL, direction text NOT NULL CHECK (direction IN ('buy','sell')),
  strategy_id text NOT NULL, payload jsonb NOT NULL,
  status text NOT NULL, executed boolean NOT NULL DEFAULT false
);
CREATE TABLE risk_evaluations (                 -- [F1]
  id bigserial PRIMARY KEY, proposal_id bigint NOT NULL REFERENCES trade_proposals(id),
  ts timestamptz NOT NULL DEFAULT now(), approved boolean NOT NULL, reason text NOT NULL,
  checks jsonb NOT NULL, limits_snapshot jsonb NOT NULL
);
CREATE TABLE risk_limits (                       -- historie van grenzen (alleen strenger)
  id bigserial PRIMARY KEY, effective_at timestamptz NOT NULL DEFAULT now(), limits jsonb NOT NULL, actor text NOT NULL
);

CREATE TABLE orders (
  id bigserial PRIMARY KEY, client_order_id text NOT NULL UNIQUE,   -- idempotentie
  account_id bigint NOT NULL REFERENCES accounts(id), proposal_id bigint REFERENCES trade_proposals(id),
  evaluation_id bigint NOT NULL REFERENCES risk_evaluations(id),    -- geen order zonder oordeel
  instrument_id bigint NOT NULL REFERENCES instruments(id),
  side text NOT NULL, type text NOT NULL, quantity numeric NOT NULL, limit_price numeric,
  status text NOT NULL CHECK (status IN ('new','submitted','partially_filled','filled','cancelled','rejected')),
  broker_order_id text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE fills (
  id bigserial PRIMARY KEY, order_id bigint NOT NULL REFERENCES orders(id), ts timestamptz NOT NULL,
  quantity numeric NOT NULL, price numeric NOT NULL, fee numeric NOT NULL, fee_currency char(3) NOT NULL,
  broker_fill_id text, UNIQUE (order_id, broker_fill_id)
);
CREATE TABLE positions (                         -- gesynchroniseerd met broker; verschil = alarm
  account_id bigint NOT NULL REFERENCES accounts(id), instrument_id bigint NOT NULL REFERENCES instruments(id),
  quantity numeric NOT NULL, avg_price numeric NOT NULL, updated_at timestamptz NOT NULL,
  PRIMARY KEY (account_id, instrument_id)
);
CREATE TABLE equity_snapshots (
  account_id bigint NOT NULL REFERENCES accounts(id), ts timestamptz NOT NULL, equity numeric NOT NULL,
  cash numeric NOT NULL, label text NOT NULL CHECK (label IN ('LIVE','SIMULATED')),
  PRIMARY KEY (account_id, ts)
);
SELECT create_hypertable('equity_snapshots', 'ts', if_not_exists => true);
