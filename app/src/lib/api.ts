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

export const getPrices = (symbols: string[]) =>
  fetchJson<ApiPrice[]>(`/market/prices?symbols=${symbols.join(',')}`);

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

export const getTrades = () => fetchJson<ApiTrade[]>('/trades');

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

// ── Market prices (bulk) ──
//
// /market/prices?symbols=A,B,C&asset_class=stock returns
// [{symbol, price, bid, ask, timestamp}]. asset_class must be one of
// 'stock'|'crypto'|'forex'. Mixed-class lookups need two calls.
export interface PriceRow {
  symbol: string;
  price: number;
  bid: number | null;
  ask: number | null;
  timestamp: string;
}

export const getPrices = (symbols: string[], assetClass: 'stock' | 'crypto' | 'forex' = 'stock') => {
  if (symbols.length === 0) return Promise.resolve([] as PriceRow[]);
  const qs = `symbols=${encodeURIComponent(symbols.join(','))}&asset_class=${assetClass}`;
  return fetchJson<PriceRow[]>(`/market/prices?${qs}`);
};

// Classify symbols by heuristic so callers can split a mixed list cheaply
// without an extra round-trip. *USD-suffix tokens and the common bare
// 3-letter coin tickers route to crypto. Everything else is stock.
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

// Bulk-fetch a mixed list, splitting crypto and stock into two parallel
// calls. Returns a single {symbol: price} map (case-preserving on the
// key the caller passed in).
export async function getPriceMap(symbols: string[]): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  if (symbols.length === 0) return out;
  const stocks: string[] = [];
  const cryptos: string[] = [];
  for (const s of symbols) {
    (classifyAsset(s) === 'crypto' ? cryptos : stocks).push(s);
  }
  const results = await Promise.allSettled([
    stocks.length ? getPrices(stocks, 'stock') : Promise.resolve([] as PriceRow[]),
    cryptos.length ? getPrices(cryptos, 'crypto') : Promise.resolve([] as PriceRow[]),
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
