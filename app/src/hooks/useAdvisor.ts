import { useState, useCallback } from 'react';

// Hit the proxied path so dev-server vite.config.ts can route to the backend.
const API_BASE = import.meta.env.VITE_API_URL || '/api';

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

export interface LLMCommentary {
  rationale: string;
  agreement: 'agrees' | 'disagrees' | 'mixed';
  adjusted_confidence: number;
  key_factors: string[];
  news_impact: 'high' | 'medium' | 'low' | 'none';
  article_count: number;
  model: string;
  alternative_verdict: string; // "" | "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL"
}

export interface AnalysisResult {
  symbol: string;
  display_name?: string;
  exchange?: string;
  sector?: string;
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
  llm_commentary: LLMCommentary | null;
}

export interface DimensionScore {
  name: string;
  score: number;
  weight: number;
  label: string;
  rationale: string;
  details?: Record<string, unknown>;
}

export interface ResearchReport {
  symbol: string;
  display_name: string;
  asset_type: string;
  current_price: number;
  overall_score: number;
  overall_label: string;
  confidence: number;
  optimal_timeframe: string;
  fundamental: DimensionScore;
  technical: DimensionScore;
  sentiment: DimensionScore;
  next_earnings_date: string | null;
  analyst_target_median: number | null;
  analyst_count: number | null;
  sector: string;
  industry: string;
  investment_thesis: string;
  key_drivers: string[];
  bull_case: string;
  bear_case: string;
  action_plan: Record<string, string>;
  bottom_line: string;
  llm_model: string;
  fundamentals_raw: Record<string, unknown>;
  generated_at: string;
}

export function useAdvisor() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [research, setResearch] = useState<ResearchReport | null>(null);
  const [researchLoading, setResearchLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(async (
    symbol: string,
    assetType: 'crypto' | 'stock' = 'crypto',
    lookbackDays = 90,
    advanced = false,
  ) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setResearch(null);
    try {
      const url = `${API_BASE}/advisor/analyze?symbol=${encodeURIComponent(symbol)}&asset_type=${assetType}&lookback_days=${lookbackDays}&advanced=${advanced ? 'true' : 'false'}`;
      const res = await fetch(url, {
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

  const fetchResearch = useCallback(async (
    symbol: string,
    assetType: 'crypto' | 'stock' = 'stock',
    lookbackDays = 365,
    advanced = false,
  ) => {
    setResearchLoading(true);
    try {
      const url = `${API_BASE}/advisor/research?symbol=${encodeURIComponent(symbol)}&asset_type=${assetType}&lookback_days=${lookbackDays}&advanced=${advanced ? 'true' : 'false'}`;
      const res = await fetch(url, { headers: { 'Content-Type': 'application/json' } });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data: ResearchReport = await res.json();
      setResearch(data);
      return data;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Research failed';
      setError(msg);
      throw e;
    } finally {
      setResearchLoading(false);
    }
  }, []);

  return { result, research, loading, researchLoading, error, analyze, fetchResearch };
}
