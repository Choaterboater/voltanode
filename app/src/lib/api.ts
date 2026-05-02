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
}

export const getPortfolio = (accountId = 'default') =>
  fetchJson<ApiPortfolio>(`/portfolio/${accountId}`);

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
