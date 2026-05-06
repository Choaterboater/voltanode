import { useState, useEffect, useCallback, useRef } from 'react';
import {
  getPortfolio,
  getPrices,
  getStrategies,
  getTrades,
  type ApiPortfolio,
  type ApiPrice,
  type ApiStrategy,
  type ApiTrade,
} from '@/lib/api';
import type { Portfolio, Position, Trade, MarketTicker } from '@/types';
import { bots, equityCurveData, alerts, performanceMetrics, assetAllocation, balanceSparkline, pnlSparkline } from '@/data/mockData';

const CRYPTO_SYMBOLS = ['bitcoin', 'ethereum', 'solana', 'avalanche-2', 'chainlink', 'polygon-ecosystem-token', 'dogecoin', 'ripple', 'cardano', 'polkadot'];
const SYMBOL_MAP: Record<string, string> = {
  bitcoin: 'BTC',
  ethereum: 'ETH',
  solana: 'SOL',
  'avalanche-2': 'AVAX',
  chainlink: 'LINK',
  'polygon-ecosystem-token': 'MATIC',
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
  return trades.map((t) => ({
    id: t.id,
    time: new Date(t.timestamp).toLocaleTimeString('en-US', { hour12: false }),
    symbol: t.symbol.replace('-', '/'),
    side: t.side === 'BUY' ? 'long' : 'short',
    price: t.price,
    size: t.quantity,
    pnl: t.realized_pnl ?? 0,
    strategy: t.strategy_id ?? 'Manual',
  }));
}

export function useDashboardData() {
  const [portfolio, setPortfolio] = useState<Portfolio>({
    totalEquity: 20000,
    availableBalance: 20000,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);
  const hasLoadedRef = useRef(false);

  const load = useCallback(async () => {
    try {
      // Only show the full-page spinner on the very first load. Background
      // polls keep stale data on screen so the dashboard doesn't flash.
      if (!hasLoadedRef.current) setLoading(true);
      const [portRes, priceRes, stratRes, tradeRes] = await Promise.all([
        getPortfolio(),
        getPrices(CRYPTO_SYMBOLS),
        getStrategies(),
        getTrades(),
      ]);
      if (cancelledRef.current) return;
      setPortfolio(mapPortfolio(portRes));
      setPositions(mapPositions(portRes));
      setTickers(mapTickers(priceRes));
      setStrategies(stratRes.strategies);
      setTrades(mapTrades(tradeRes));
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
    // Keep mock fallbacks for rich UI sections backend doesn't serve yet
    bots,
    equityCurveData,
    alerts,
    performanceMetrics,
    assetAllocation,
    balanceSparkline,
    pnlSparkline,
  };
}
