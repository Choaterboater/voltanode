import { useState, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface PortfolioData {
  account_id: string;
  balances: Record<string, number>;
  positions: Array<{
    symbol: string;
    side: string;
    size: number;
    entry_price: number;
    current_price: number;
    unrealized_pnl: number;
    market_value: number;
  }>;
  unrealized_pnl: number;
  realized_pnl: number;
  total_equity?: number;
}

export interface TradeData {
  id: string;
  order_id: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  realized_pnl: number | null;
  timestamp: string;
}

export interface BotStatus {
  running: boolean;
  account_count: number;
}

export interface MarketPrice {
  symbol: string;
  price: number;
  change24h: number;
  change24h_percent: number;
  volume24h: number;
  high24h: number;
  low24h: number;
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export function usePortfolio() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPortfolio = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const portfolio = await fetchJson<PortfolioData>('/portfolio/default');
      setData(portfolio);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load portfolio');
    } finally {
      setLoading(false);
    }
  }, []);

  return { data, loading, error, refresh: fetchPortfolio };
}

export function useTrades() {
  const [data, setData] = useState<TradeData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const trades = await fetchJson<TradeData[]>('/trades');
      setData(trades);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load trades');
    } finally {
      setLoading(false);
    }
  }, []);

  return { data, loading, error, refresh: fetchTrades };
}

export function useEngineStatus() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const s = await fetchJson<BotStatus>('/engine/status');
      setStatus(s);
    } catch {
      setStatus({ running: false, account_count: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  const startEngine = useCallback(async () => {
    await fetchJson('/engine/start', { method: 'POST' });
    fetchStatus();
  }, [fetchStatus]);

  const stopEngine = useCallback(async () => {
    await fetchJson('/engine/stop', { method: 'POST' });
    fetchStatus();
  }, [fetchStatus]);

  return { status, loading, refresh: fetchStatus, startEngine, stopEngine };
}

export function useMarketPrices() {
  const [prices, setPrices] = useState<MarketPrice[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchPrices = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchJson<{ prices: MarketPrice[] }>('/market/prices');
      setPrices(data.prices || []);
    } catch {
      setPrices([]);
    } finally {
      setLoading(false);
    }
  }, []);

  return { prices, loading, refresh: fetchPrices };
}
