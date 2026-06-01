const API_BASE = import.meta.env.VITE_API_URL || '/api';

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text().catch(() => 'Unknown error');
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

// ── Health / Engine ──
export const getHealth = () => fetchJson<{ status: string; version: string }>('/health');
export const getEngineStatus = () => fetchJson<{ running: boolean; account_count: number }>('/engine/status');
export const startEngine = () => fetchJson<{ status: string }>('/engine/start', { method: 'POST' });
export const stopEngine = () => fetchJson<{ status: string }>('/engine/stop', { method: 'POST' });

/** Restart the backend process. Returns immediately; the backend dies in ~2s
 *  and a fresh one spawns in a new console window. Poll /engine/status to
 *  detect when it's back up. */
export const restartBackend = () =>
  fetchJson<{ scheduled: boolean; pid_to_kill: number; estimated_downtime_sec: number }>(
    '/settings/restart',
    { method: 'POST' },
  );

export interface ApiSafetyStatus {
  live_mode: boolean;
  broker_connected: boolean;
  kill_switch: {
    activated: boolean;
    reason?: string | null;
    activated_at?: string | null;
  };
  daily_tracker: Record<string, unknown>;
  safety_limits: {
    max_exposure_pct?: number;
    max_position_size_pct?: number;
    max_orders_per_minute?: number;
    orders_remaining_this_minute?: number;
    [key: string]: unknown;
  };
}

export const getSafetyStatus = () => fetchJson<ApiSafetyStatus>('/settings/safety-status');

// ── Portfolio ──
export interface ApiPortfolio {
  account_id: string;
  balances: Record<string, number>;
  positions: ApiPosition[];
  total_equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  timestamp: string;
}

export interface ApiPosition {
  symbol: string;
  side: 'LONG' | 'SHORT';
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  opened_at: string;
  stop_loss?: number;
  take_profit?: number;
}

export const getPortfolio = (accountId = 'default') =>
  fetchJson<ApiPortfolio>(`/portfolio/${accountId}`);

export interface EquityPoint {
  ts: string;
  equity: number;
}

export const getEquityHistory = (
  accountId = 'default',
  range: '1H' | '24H' | '7D' | '30D' | 'ALL' = '30D',
) =>
  fetchJson<{ account_id: string; range: string; points: EquityPoint[] }>(
    `/portfolio/${accountId}/equity-history?range=${range}`,
  );

export interface PortfolioStats {
  account_id: string;
  range: string;
  equity_curve: EquityPoint[];
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  profit_factor: number | null;
  total_trades: number;
}

export const getPortfolioStats = (
  accountId = 'default',
  range: '1H' | '24H' | '7D' | '30D' | 'ALL' = '24H',
) => fetchJson<PortfolioStats>(`/portfolio/${accountId}/stats?range=${range}`);

// ── Signals (macro / sentiment / catalysts) ──

export interface FearGreedSignal {
  value: number;
  label: string;
  is_extreme_fear: boolean;
  is_extreme_greed: boolean;
  timestamp: string;
}

export interface MacroSeries {
  value: number | null;
  date: string;
  change: number | null;
  name: string;
}

export interface SignalsSnapshot {
  fear_greed?: FearGreedSignal;
  macro?: { fetched_at: string; series: Record<string, MacroSeries> };
  providers: { fear_greed: boolean; fred: boolean; finnhub: boolean };
}

export const getSignals = () => fetchJson<SignalsSnapshot>('/signals/');

export interface EarningsEntry {
  symbol: string;
  date: string;
  days_until?: number | null;
  eps_estimate: number | null;
  revenue_estimate: number | null;
  hour: string;
}

export const getEarningsCalendar = (daysAhead = 7) =>
  fetchJson<{ days_ahead: number; count: number; entries: EarningsEntry[] }>(
    `/signals/earnings?days_ahead=${daysAhead}`,
  );

export const getInsiderSummary = (symbol: string) =>
  fetchJson<{
    symbol: string;
    buys: number;
    sells: number;
    buy_value_usd: number;
    sell_value_usd: number;
    net_value_usd: number;
    tone: 'bullish' | 'bearish' | 'neutral';
  }>(`/signals/insider/${symbol}`);

// ── Market Data ──
export interface ApiPrice {
  symbol: string;
  price: number;
  bid: number | null;
  ask: number | null;
  timestamp: string;
}

export const getPrices = (symbols: string[], assetClass: 'stock' | 'crypto' | 'forex' = 'crypto') => {
  if (symbols.length === 0) return Promise.resolve([] as ApiPrice[]);
  const qs = `symbols=${encodeURIComponent(symbols.join(','))}&asset_class=${assetClass}`;
  return fetchJson<ApiPrice[]>(`/market/prices?${qs}`);
};

// ── Long-term picks ──
// GET /advisor/long-term — year+ holding screener (50% fundamentals / 30% trend /
// 20% low-vol composite). Defaults to S&P 500; pass symbols=A,B,C for a custom universe.
export interface LongTermComponent {
  score: number;
  value: number | null;
  signal: string;
}
export interface LongTermPick {
  symbol: string;
  name: string;
  sector: string;
  score: number;
  current_price: number;
  bars: number;
  components: Record<'fundamentals' | 'trend' | 'low_volatility', LongTermComponent>;
  error: string | null;
}
export interface LongTermResponse {
  asset_class: string;
  scanned_at: string;
  elapsed_ms: number;
  universe_size: number;
  scored: number;
  weights: Record<string, number>;
  results: LongTermPick[];
  failed: { symbol: string; error: string | null }[];
}
export const getLongTermPicks = (params: {
  asset_class?: 'stock' | 'crypto';
  top?: number;
  min_score?: number;
  limit_universe?: number;
  symbols?: string;
  sector?: string;
  weight_fundamentals?: number;
  weight_trend?: number;
  weight_low_volatility?: number;
  max_price?: number;
  min_price?: number;
} = {}) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return fetchJson<LongTermResponse>(`/advisor/long-term${suffix}`);
};

export const getOHLCV = (symbol: string, assetClass = 'crypto', timeframe = '1d', limit = 100) =>
  fetchJson<{ timestamp: string; open: number; high: number; low: number; close: number; volume: number }[]>(
    `/market/ohlcv?symbol=${symbol}&asset_class=${assetClass}&timeframe=${timeframe}&limit=${limit}`
  );

// ── Strategies ──
export interface ApiStrategy {
  strategy_id: string;
  strategy_type: string;
  is_active: boolean;
  config: Record<string, unknown>;
  metrics: Record<string, unknown> | null;
}

export const getStrategies = () => fetchJson<{ strategies: ApiStrategy[] }>('/strategies');

export const registerStrategy = (strategyType: string, config?: Record<string, unknown>) =>
  fetchJson<{ strategy_id: string; strategy_type: string; status: string }>('/strategies/register', {
    method: 'POST',
    body: JSON.stringify({ strategy_type: strategyType, config }),
  });

export const toggleStrategy = (strategyId: string, active: boolean) =>
  fetchJson<{ strategy_id: string; active: boolean }>(`/strategies/${strategyId}/toggle`, {
    method: 'POST',
    body: JSON.stringify({ strategy_id: strategyId, active }),
  });

// ── Orders ──
export interface ApiOrder {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  order_type: 'market' | 'limit' | 'stop_loss' | 'take_profit' | 'stop_limit';
  quantity: number;
  price: number | null;
  stop_price: number | null;
  status: 'pending' | 'filled' | 'cancelled' | 'rejected';
  created_at: string;
  strategy_id: string | null;
  account_id: string;
}

export const getOrders = (accountId = 'default') =>
  fetchJson<ApiOrder[]>(`/orders?account_id=${accountId}`);

export const placeOrder = (payload: {
  symbol: string;
  side: 'buy' | 'sell';
  order_type: 'market' | 'limit' | 'stop_loss';
  quantity: number;
  price?: number;
  stop_price?: number;
  account_id?: string;
  strategy_id?: string;
}) =>
  fetchJson<{ order_id: string; status: string; filled_qty: number; avg_fill_price?: number; fee: number }>(
    '/orders',
    { method: 'POST', body: JSON.stringify(payload) }
  );

export const cancelOrder = (orderId: string, accountId = 'default') =>
  fetchJson<{ order_id: string; status: string }>(`/orders/${orderId}/cancel?account_id=${accountId}`, { method: 'POST' });

// ── Trades ──
export interface ApiTrade {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  fee: number;
  timestamp: string;
  realized_pnl: number | null;
  strategy_id: string | null;
}

export const getTrades = (limit?: number) =>
  fetchJson<ApiTrade[]>(limit ? `/trades/?limit=${limit}` : '/trades');

// ── Settings ──
export interface LiveModeStatus {
  live_mode: boolean;
  broker_name: string;
  broker_connected: boolean;
  confirmation_required: boolean;
}

export const getLiveMode = () => fetchJson<LiveModeStatus>('/settings/live-mode');

// ── Backtest ──
export interface BacktestPayload {
  strategy_id: string;
  symbol: string;
  asset_class: string;
  timeframe: string;
  start_date?: string;
  end_date?: string;
  initial_balance?: Record<string, number>;
}

export const runBacktest = (payload: BacktestPayload) =>
  fetchJson<{
    backtest_id: string;
    strategy_id: string;
    total_return_pct: number;
    sharpe_ratio: number;
    max_drawdown_pct: number;
    win_rate: number;
    profit_factor: number;
    total_trades: number;
    equity_curve: { timestamp?: string; equity: number }[];
  }>('/backtest/run', { method: 'POST', body: JSON.stringify(payload) });

export const getBacktestResults = () =>
  fetchJson<{ results: unknown[] }>('/backtest/results');

// ── News & Sentiment ──
export interface NewsStatus {
  alpaca_configured: boolean;
  llm_provider: string | null;
  llm_configured: boolean;
  hybrid_mode: boolean;
  hybrid_threshold: number;
  vader_available: boolean;
  ollama_available: boolean;
  timestamp: string;
}

export interface SentimentResult {
  article_id: string;
  symbol: string;
  compound_score: number;
  positive_score: number;
  negative_score: number;
  neutral_score: number;
  confidence: number;
  model: string;
  impact_assessment: string;
  key_themes: string[];
  analyzed_at: string;
}

export interface AnalyzeResponse {
  headline: string;
  symbols: string[];
  results: SentimentResult[];
}

export interface SymbolSentimentSummary {
  symbol: string;
  article_count: number;
  avg_compound: number;
  sentiment_label: string;
  latest_headlines: string[];
  trending: boolean;
  updated_at: string;
}

export interface SymbolSentimentResponse {
  symbol: string;
  scores: SentimentResult[];
  summary: SymbolSentimentSummary | null;
}

export interface TrendingSymbol {
  symbol: string;
  article_count: number;
  avg_compound: number;
  sentiment_label: string;
  latest_headlines: string[];
  trending: boolean;
  updated_at: string;
}

export const getNewsStatus = () => fetchJson<NewsStatus>('/news/status');

export const analyzeHeadline = (headline: string, summary = '', source = 'manual', symbols: string[] = []) =>
  fetchJson<AnalyzeResponse>(`/news/analyze?headline=${encodeURIComponent(headline)}&summary=${encodeURIComponent(summary)}&source=${encodeURIComponent(source)}${symbols.map(s => `&symbols=${encodeURIComponent(s)}`).join('')}`, { method: 'POST' });

export const getSymbolSentiment = (symbol: string, hours = 24) =>
  fetchJson<SymbolSentimentResponse>(`/news/sentiment/${symbol}?hours=${hours}`);

export const getTrendingSymbols = (hours = 24, minArticles = 3) =>
  fetchJson<TrendingSymbol[]>(`/news/trending?hours=${hours}&min_articles=${minArticles}`);

// ── News velocity + impact (analytics layer) ──
export interface VelocityWindow {
  hours: number;
  article_count: number;
  avg_compound: number;
  max_compound: number;
  min_compound: number;
}
export interface VelocitySnapshot {
  symbol: string;
  computed_at: string;
  windows: VelocityWindow[];
  velocity: number;
  velocity_label: string;
  acceleration: number;
  fresh_article_pct: number;
  error: string | null;
}
export const getNewsVelocity = (symbol: string, windows?: string) => {
  const qs = windows ? `?windows=${encodeURIComponent(windows)}` : '';
  return fetchJson<VelocitySnapshot>(`/news/velocity/${encodeURIComponent(symbol)}${qs}`);
};

export interface ImpactBucket {
  score_low: number;
  score_high: number;
  horizon_days: number;
  n: number;
  mean_return_pct: number;
  median_return_pct: number;
  hit_rate: number;
  stdev_return_pct: number;
}
export interface ImpactReport {
  generated_at: string;
  lookback_days: number;
  symbols: string[];
  article_count: number;
  skipped_count: number;
  buckets: ImpactBucket[];
  by_symbol: Record<string, { n_articles?: number; mean_short_horizon_return_pct?: number | null; skipped?: boolean; reason?: string }>;
  error: string | null;
}
export const getNewsImpact = (params: {
  symbols: string;
  lookback_days?: number;
  horizons?: string;
} ) => {
  const qs = new URLSearchParams();
  qs.set('symbols', params.symbols);
  if (params.lookback_days !== undefined) qs.set('lookback_days', String(params.lookback_days));
  if (params.horizons) qs.set('horizons', params.horizons);
  return fetchJson<ImpactReport>(`/news/impact?${qs.toString()}`);
};

// Classify a symbol as stock or crypto by heuristic so getPriceMap can
// route a mixed list to the right asset_class without an extra round-trip.
// *USD/USDT/USDC suffixes and the common bare coin tickers → crypto.
const CRYPTO_BARE = new Set([
  'BTC', 'ETH', 'SOL', 'AVAX', 'BNB', 'XRP', 'ADA', 'DOGE', 'SHIB', 'LTC',
  'BCH', 'LINK', 'DOT', 'MATIC', 'TRX', 'UNI', 'AAVE', 'YFI', 'MKR', 'SUSHI',
]);

export function classifyAsset(symbol: string): 'stock' | 'crypto' {
  const s = symbol.toUpperCase();
  if (s.endsWith('USD') || s.endsWith('USDT') || s.endsWith('USDC')) return 'crypto';
  if (CRYPTO_BARE.has(s)) return 'crypto';
  return 'stock';
}

// Bulk-fetch prices for a mixed-asset symbol list. Splits into stock vs
// crypto by classifyAsset(), hits /market/prices for each in parallel,
// returns a flat {SYMBOL: price} map. Failed sub-calls are silent —
// prices are decoration, not load-bearing.
export async function getPriceMap(symbols: string[]): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  if (symbols.length === 0) return out;
  const stocks: string[] = [];
  const cryptos: string[] = [];
  for (const s of symbols) {
    (classifyAsset(s) === 'crypto' ? cryptos : stocks).push(s);
  }
  const results = await Promise.allSettled([
    stocks.length ? getPrices(stocks, 'stock') : Promise.resolve([] as ApiPrice[]),
    cryptos.length ? getPrices(cryptos, 'crypto') : Promise.resolve([] as ApiPrice[]),
  ]);
  for (const r of results) {
    if (r.status === 'fulfilled') {
      for (const row of r.value) {
        if (row && typeof row.price === 'number') out[row.symbol] = row.price;
      }
    }
  }
  return out;
}
