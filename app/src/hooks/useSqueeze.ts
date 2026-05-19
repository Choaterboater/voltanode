import { useCallback, useEffect, useState } from 'react';

// Hit the proxied path so dev-server vite.config.ts can route to the backend.
const API_BASE = import.meta.env.VITE_API_URL || '/api';

// Module-level cache so navigating away and back doesn't trigger a fresh
// 10-15s scan every time. Cache persists for ``CACHE_TTL_MS`` from the most
// recent successful scan; navigation simply rehydrates from this singleton.
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes
let _cachedResult: SqueezeResponse | null = null;
let _cachedAt = 0;
let _cachedKey = '';

function makeCacheKey(opts: SqueezeOptions): string {
  // Only include params that affect the response.
  return JSON.stringify({
    daysBack: opts.daysBack ?? 7,
    minScore: opts.minScore ?? 0,
    tier: opts.tier ?? null,
    extraSymbols: opts.extraSymbols ?? null,
    fetchTechnical: opts.fetchTechnical ?? true,
    maxResults: opts.maxResults ?? 50,
    maxPrice: opts.maxPrice === undefined ? 20 : opts.maxPrice,
    minMarketCap: opts.minMarketCap ?? null,
    maxMarketCap: opts.maxMarketCap ?? null,
    maxFloatShares: opts.maxFloatShares ?? null,
    minPrice: opts.minPrice ?? null,
    minAvgDailyVolume: opts.minAvgDailyVolume ?? null,
    sectorBlocklist: opts.sectorBlocklist ?? null,
  });
}

export interface SqueezeFactors {
  short_interest: number;
  float_size: number;
  days_to_cover: number;
  earnings_trend: number;
  recent_13d: number;
  technical: number;
  off_exchange_short: number;
}

export interface SqueezeFiling {
  form: string;
  filed_at: string;
  filer_name: string;
  edgar_url: string;
}

export interface SqueezeFinra {
  trade_date: string;
  short_volume_total: number;
  total_volume: number;
  short_pct_total: number;
  off_exchange_short_volume: number;
  off_exchange_total_volume: number;
  off_exchange_short_pct: number;
}

export interface QuarterlyEPS {
  period_end: string;
  eps: number | null;
  estimate: number | null;
  surprise_pct: number | null;
}

export interface SqueezeResult {
  ticker: string;
  name: string;
  sector: string;
  industry: string;
  market_cap: number | null;
  float_shares: number | null;
  current_price: number | null;
  avg_daily_volume_10d: number | null;
  short_pct_of_float: number | null;
  days_to_cover: number | null;
  earnings_qoq_growth: number | null;
  earnings_growth_yoy: number | null;
  // True iff yfinance actually returned earnings-growth fields. Lets
  // the UI render "—" when has_earnings_data=false instead of "+0.0%"
  // for a missing-field row.
  has_earnings_data?: boolean;
  next_earnings_date: string | null;
  has_recent_13d_filing: boolean;
  quarterly_eps: QuarterlyEPS[];
  scanner_score: number | null;
  day_pct_change: number | null;
  sparkline: number[] | null;
  score: number;
  tier: 'ADD' | 'WATCHLIST' | 'BASE' | 'DISMISS';
  factors: SqueezeFactors;
  factor_notes: Record<string, string>;
  warnings: string[];
  finra?: SqueezeFinra;
  filing?: SqueezeFiling;
}

export interface SqueezeResponse {
  scanned_at: string;
  elapsed_ms: number;
  filters: Record<string, unknown>;
  filings_count: number;
  candidates_scored: number;
  passed_filters: number;
  errors_count: number;
  finra_trade_date: string | null;
  results: SqueezeResult[];
  rejected_sample: { ticker: string; reason: string }[];
  errors_sample: { ticker: string; error: string }[];
  data_caveats: string[];
}

export interface SqueezeOptions {
  daysBack?: number;
  minScore?: number;
  tier?: string;
  extraSymbols?: string;
  fetchTechnical?: boolean;
  maxResults?: number;
  minMarketCap?: number;
  maxMarketCap?: number;
  maxFloatShares?: number;
  minPrice?: number;
  maxPrice?: number | null; // null/0 disables ceiling
  minAvgDailyVolume?: number;
  sectorBlocklist?: string;
  concurrency?: number;
}

export function useSqueeze() {
  // Rehydrate from module-level cache on mount — keeps results visible across
  // navigations without re-firing a 10-15s scan.
  const [result, setResult] = useState<SqueezeResponse | null>(_cachedResult);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep state in sync if the cache changes between mounts.
  useEffect(() => {
    if (_cachedResult && !result) setResult(_cachedResult);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runScan = useCallback(
    async (opts: SqueezeOptions = {}, options: { force?: boolean } = {}) => {
      const key = makeCacheKey(opts);
      const fresh = Date.now() - _cachedAt < CACHE_TTL_MS;
      if (!options.force && _cachedResult && _cachedKey === key && fresh) {
        // Cache hit — surface the cached payload without hitting the backend.
        setResult(_cachedResult);
        return _cachedResult;
      }
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        params.set('days_back', String(opts.daysBack ?? 7));
        params.set('min_score', String(opts.minScore ?? 0));
        if (opts.tier) params.set('tier', opts.tier);
        if (opts.extraSymbols) params.set('extra_symbols', opts.extraSymbols);
        params.set('fetch_technical', String(opts.fetchTechnical ?? true));
        params.set('max_results', String(opts.maxResults ?? 50));
        if (opts.minMarketCap !== undefined)
          params.set('min_market_cap', String(opts.minMarketCap));
        if (opts.maxMarketCap !== undefined)
          params.set('max_market_cap', String(opts.maxMarketCap));
        if (opts.maxFloatShares !== undefined)
          params.set('max_float_shares', String(opts.maxFloatShares));
        if (opts.minPrice !== undefined)
          params.set('min_price', String(opts.minPrice));
        if (opts.maxPrice !== undefined && opts.maxPrice !== null)
          params.set('max_price', String(opts.maxPrice));
        else if (opts.maxPrice === null) params.set('max_price', '0');
        if (opts.minAvgDailyVolume !== undefined)
          params.set('min_avg_daily_volume', String(opts.minAvgDailyVolume));
        if (opts.sectorBlocklist)
          params.set('sector_blocklist', opts.sectorBlocklist);
        if (opts.concurrency !== undefined)
          params.set('concurrency', String(opts.concurrency));

        const res = await fetch(
          `${API_BASE}/advisor/squeeze?${params.toString()}`,
        );
        if (!res.ok) {
          const msg = await res.text().catch(() => '');
          throw new Error(`HTTP ${res.status} ${msg.slice(0, 200)}`);
        }
        const data = (await res.json()) as SqueezeResponse;
        // Update module-level cache so other mounts of this hook can rehydrate.
        _cachedResult = data;
        _cachedAt = Date.now();
        _cachedKey = key;
        setResult(data);
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        throw e;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  /** Resolve a free-text query (ticker OR company name) to a list of stock
   * symbol hits via the existing /advisor/lookup endpoint. Used by the
   * "extra symbols" typeahead. */
  const lookupSymbols = useCallback(
    async (
      query: string,
      limit = 6,
    ): Promise<{ symbol: string; name: string; asset_type: string }[]> => {
      if (!query.trim()) return [];
      try {
        const r = await fetch(
          `${API_BASE}/advisor/lookup?q=${encodeURIComponent(query)}&limit=${limit}`,
        );
        if (!r.ok) return [];
        const d = await r.json();
        const hits = Array.isArray(d?.hits) ? d.hits : [];
        // Squeeze screener is stock-only; drop crypto results.
        return hits.filter(
          (h: { asset_type?: string }) => (h.asset_type ?? '') === 'stock',
        );
      } catch {
        return [];
      }
    },
    [],
  );

  return { result, loading, error, runScan, lookupSymbols };
}
