import { useState, useEffect, useCallback, useRef } from 'react';
import {
  getPortfolio,
  getPrices,
  getStrategies,
  getTrades,
  getEquityHistory,
  type ApiPortfolio,
  type ApiPrice,
  type ApiStrategy,
  type ApiTrade,
  type EquityPoint,
} from '@/lib/api';
import type { Portfolio, Position, Trade, MarketTicker } from '@/types';
import { bots, alerts } from '@/data/mockData';

export interface AllocationSlice { name: string; value: number; color: string }
export interface PerformanceMetrics {
  winRate: number | null;
  sharpeRatio: number | null;
  maxDrawdownPercent: number | null;
  profitFactor: number | null;
  tradesPerDay: number | null;
  totalTrades: number;
}

const ALLOC_PALETTE = ['#06B6D4', '#A78BFA', '#10B981', '#F59E0B', '#EF4444', '#22D3EE', '#F472B6', '#84CC16'];

function deriveAllocation(api: ApiPortfolio): AllocationSlice[] {
  const slices: AllocationSlice[] = [];
  const total = api.total_equity || 1;
  api.positions.forEach((p, i) => {
    const value = p.size * p.current_price;
    if (value > 0) {
      slices.push({
        name: p.symbol.replace(/USD$/, '').replace(/USDT$/, ''),
        value: Math.round((value / total) * 1000) / 10,
        color: ALLOC_PALETTE[i % ALLOC_PALETTE.length],
      });
    }
  });
  const cash = api.balances?.USD ?? 0;
  if (cash > 0) {
    slices.push({ name: 'USD', value: Math.round((cash / total) * 1000) / 10, color: '#64748B' });
  }
  return slices;
}

function derivePerformance(trades: Trade[]): PerformanceMetrics {
  const closed = trades.filter(t => t.pnl !== 0);
  const total = closed.length;
  if (total === 0) {
    return { winRate: null, sharpeRatio: null, maxDrawdownPercent: null, profitFactor: null, tradesPerDay: null, totalTrades: 0 };
  }
  const wins = closed.filter(t => t.pnl > 0);
  const winRate = (wins.length / total) * 100;
  const grossWin = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(closed.filter(t => t.pnl < 0).reduce((s, t) => s + t.pnl, 0));
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : null;
  return { winRate, sharpeRatio: null, maxDrawdownPercent: null, profitFactor, tradesPerDay: null, totalTrades: total };
}

const CRYPTO_SYMBOLS = ['bitcoin', 'ethereum', 'solana', 'avalanche-2', 'chainlink', 'matic-network', 'dogecoin', 'ripple', 'cardano', 'polkadot'];
const SYMBOL_MAP: Record<string, string> = {
  bitcoin: 'BTC',
  ethereum: 'ETH',
  solana: 'SOL',
  'avalanche-2': 'AVAX',
  chainlink: 'LINK',
  'matic-network': 'MATIC',
  dogecoin: 'DOGE',
  ripple: 'XRP',
  cardano: 'ADA',
  polkadot: 'DOT',
};

function mapPortfolio(api: ApiPortfolio): Portfolio {
  const totalEquity = api.total_equity;
  const realizedPnl = api.realized_pnl;
  // Estimate daily PnL from unrealized if no daily tracker exists
  const dailyPnl = api.unrealized_pnl;
  const dailyPnlPercent = totalEquity > 0 ? (dailyPnl / totalEquity) * 100 : 0;
  return {
    totalEquity,
    availableBalance: totalEquity - api.positions.reduce((s, p) => s + p.size * p.current_price, 0),
    marginUsed: api.positions.reduce((s, p) => s + p.size * p.current_price, 0),
    dailyPnl,
    dailyPnlPercent,
    totalPnl: realizedPnl,
    totalPnlPercent: totalEquity > 0 ? (realizedPnl / totalEquity) * 100 : 0,
  };
}

function mapPositions(api: ApiPortfolio): Position[] {
  return api.positions.map((p, i) => {
    const sideUpper = String(p.side ?? '').toUpperCase();
    const isShort = sideUpper === 'SHORT';
    return {
      id: `pos-${i}`,
      symbol: p.symbol.replace('-', '/'),
      side: isShort ? 'short' : 'long',
      size: p.size,
      entryPrice: p.entry_price,
      markPrice: p.current_price,
      pnl: p.unrealized_pnl,
      pnlPercent:
        p.entry_price > 0
          ? ((p.current_price - p.entry_price) / p.entry_price) * 100 * (isShort ? -1 : 1)
          : 0,
      openedAt: p.opened_at,
    };
  });
}

function mapTickers(prices: ApiPrice[]): MarketTicker[] {
  return prices.map((p) => ({
    symbol: SYMBOL_MAP[p.symbol] || p.symbol.toUpperCase(),
    price: p.price,
    change24h: 0,
    change24hPercent: 0,
    volume24h: 0,
    high24h: p.price * 1.02,
    low24h: p.price * 0.98,
  }));
}

function mapTrades(trades: ApiTrade[]): Trade[] {
  return trades.map((t) => {
    // Backend ``OrderSide`` enum serializes lowercase ('buy'/'sell'); the
    // older comparison against 'BUY' bucketed everything as 'short'.
    const sideRaw = String(t.side ?? '').toLowerCase();
    return {
      id: t.id,
      time: new Date(t.timestamp).toLocaleTimeString('en-US', { hour12: false }),
      symbol: t.symbol.replace('-', '/'),
      side: sideRaw === 'buy' ? 'long' : 'short',
      price: t.price,
      size: t.quantity,
      pnl: t.realized_pnl ?? 0,
      strategy: t.strategy_id ?? 'Manual',
    };
  });
}

export function useDashboardData() {
  const [portfolio, setPortfolio] = useState<Portfolio>({
    totalEquity: 0,
    availableBalance: 0,
    marginUsed: 0,
    dailyPnl: 0,
    dailyPnlPercent: 0,
    totalPnl: 0,
    totalPnlPercent: 0,
  });
  const [positions, setPositions] = useState<Position[]>([]);
  const [tickers, setTickers] = useState<MarketTicker[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [strategies, setStrategies] = useState<ApiStrategy[]>([]);
  const [equityHistory, setEquityHistory] = useState<EquityPoint[]>([]);
  const [allocation, setAllocation] = useState<AllocationSlice[]>([]);
  const [perf, setPerf] = useState<PerformanceMetrics>({
    winRate: null, sharpeRatio: null, maxDrawdownPercent: null, profitFactor: null, tradesPerDay: null, totalTrades: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);
  const hasLoadedRef = useRef(false);

  const load = useCallback(async () => {
    try {
      // Only show the full-page spinner on the very first load. Background
      // polls keep stale data on screen so the dashboard doesn't flash.
      if (!hasLoadedRef.current) setLoading(true);
      const [portRes, priceRes, stratRes, tradeRes, equityRes] = await Promise.all([
        getPortfolio(),
        getPrices(CRYPTO_SYMBOLS),
        getStrategies(),
        getTrades(),
        getEquityHistory('default', '30D').catch(() => ({ points: [] as EquityPoint[] })),
      ]);
      if (cancelledRef.current) return;
      setPortfolio(mapPortfolio(portRes));
      setPositions(mapPositions(portRes));
      setTickers(mapTickers(priceRes));
      setStrategies(stratRes.strategies);
      const mapped = mapTrades(tradeRes);
      setTrades(mapped);
      setEquityHistory(equityRes.points || []);
      setAllocation(deriveAllocation(portRes));
      setPerf(derivePerformance(mapped));
      setError(null);
      hasLoadedRef.current = true;
    } catch (e) {
      if (cancelledRef.current) return;
      setError(e instanceof Error ? e.message : 'Failed to load dashboard data');
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;
    hasLoadedRef.current = false;
    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, [load]);

  return {
    portfolio,
    positions,
    tickers,
    trades,
    strategies,
    loading,
    error,
    refetch: load,
    bots,
    alerts,
    equityHistory,
    allocation,
    performance: perf,
  };
}
