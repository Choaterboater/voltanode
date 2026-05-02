import { useState, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface IndicatorReading {
  name: string;
  value: number;
  signal: 'bullish' | 'bearish' | 'neutral';
  strength: number;
  description: string;
}

export interface PriceTarget {
  label: string;
  price: number;
  probability: number;
  rationale: string;
}

export interface ChartData {
  timestamps: string[];
  ohlcv: {
    open: number[];
    high: number[];
    low: number[];
    close: number[];
    volume: number[];
  };
  sma_20?: (number | null)[];
  sma_50?: (number | null)[];
  ema_20?: (number | null)[];
  ema_50?: (number | null)[];
  vwap?: (number | null)[];
  bb_upper?: (number | null)[];
  bb_lower?: (number | null)[];
  macd?: (number | null)[];
  macd_signal?: (number | null)[];
  macd_hist?: (number | null)[];
  rsi?: (number | null)[];
  supertrend?: (number | null)[];
  tenkan?: (number | null)[];
  kijun?: (number | null)[];
  adx?: (number | null)[];
}

export interface AnalysisResult {
  symbol: string;
  current_price: number;
  asset_type: string;
  verdict: string;
  confidence: number;
  summary: string;
  indicators: IndicatorReading[];
  price_targets: PriceTarget[];
  risk_level: string;
  suggested_position_size: number;
  entry_zone_low: number;
  entry_zone_high: number;
  stop_loss: number;
  take_profit: number;
  time_horizon: string;
  chart_data: ChartData;
}

export function useAdvisor() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(async (symbol: string, assetType: 'crypto' | 'stock' = 'crypto', lookbackDays = 90) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/advisor/analyze?symbol=${encodeURIComponent(symbol)}&asset_type=${assetType}&lookback_days=${lookbackDays}`, {
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data: AnalysisResult = await res.json();
      setResult(data);
      return data;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Analysis failed';
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  return { result, loading, error, analyze };
}
