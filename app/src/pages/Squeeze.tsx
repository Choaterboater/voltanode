import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  ExternalLink,
  Flame,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
} from 'lucide-react';
import { toast } from 'sonner';
import Layout from '@/components/Layout';
import { useSqueeze, type SqueezeResult } from '@/hooks/useSqueeze';
import { useWatchlist } from '@/hooks/useWatchlist';

type TierFilter = 'ALL' | 'ADD' | 'WATCHLIST' | 'BASE';

type SortKey =
  | 'score'
  | 'ticker'
  | 'current_price'
  | 'day_pct_change'
  | 'short_pct_of_float'
  | 'days_to_cover'
  | 'float_shares'
  | 'off_exchange_short_pct'
  | 'earnings_qoq_growth'
  | 'market_cap'
  | 'scanner_score';

type SortDir = 'asc' | 'desc';

const TIER_STYLES: Record<string, string> = {
  ADD: 'bg-success-green/15 text-success-green border-success-green/40',
  WATCHLIST: 'bg-accent-cyan/15 text-accent-cyan border-accent-cyan/40',
  BASE: 'bg-bg-elevated text-text-muted border-border-subtle',
  DISMISS: 'bg-bg-elevated/50 text-text-muted/60 border-border-subtle',
};

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(0)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtShares(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
}

function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return '—';
  return `${(n * 100).toFixed(decimals)}%`;
}

function fmtPctRaw(n: number | null | undefined, decimals = 1): string {
  if (n == null) return '—';
  return `${n.toFixed(decimals)}%`;
}

interface SortHeaderProps {
  k: SortKey;
  cur: SortKey;
  dir: SortDir;
  onClick: (k: SortKey) => void;
  children: React.ReactNode;
  className?: string;
}

function SortHeader({
  k,
  cur,
  dir,
  onClick,
  children,
  className = 'px-2 py-3',
}: SortHeaderProps) {
  const active = cur === k;
  return (
    <th
      onClick={() => onClick(k)}
      className={`${className} cursor-pointer select-none hover:text-text-primary transition-colors`}
    >
      <div className="inline-flex items-center gap-1">
        <span className={active ? 'text-accent-cyan' : ''}>{children}</span>
        {active && (
          dir === 'asc' ? (
            <ArrowUp className="h-3 w-3 text-accent-cyan" />
          ) : (
            <ArrowDown className="h-3 w-3 text-accent-cyan" />
          )
        )}
      </div>
    </th>
  );
}

interface SparklineProps {
  values: number[];
  color: string; // tailwind text-* class for the stroke
  width?: number;
  height?: number;
}

interface QuarterlyEarningsChartProps {
  quarters: { period_end: string; eps: number | null; estimate: number | null }[];
  width?: number;
  height?: number;
}

/** Bar chart of last N quarters of reported EPS — green if EPS > 0, red if < 0,
 * with a faint marker for analyst estimate. Drives the "earnings trending up
 * + high SI = squeeze precursor" intuition (RXT pattern). */
function QuarterlyEarningsChart({
  quarters,
  width = 220,
  height = 80,
}: QuarterlyEarningsChartProps) {
  if (!quarters || quarters.length === 0) {
    return (
      <div className="text-text-muted text-[10px]">
        No quarterly EPS history available.
      </div>
    );
  }
  const eps = quarters.map((q) => q.eps ?? 0);
  const ests = quarters.map((q) => q.estimate);
  const min = Math.min(0, ...eps, ...(ests.filter((e) => e != null) as number[]));
  const max = Math.max(0, ...eps, ...(ests.filter((e) => e != null) as number[]));
  const range = max - min || 1;
  const zeroY = height - ((0 - min) / range) * height;
  const padding = 8;
  const innerW = width - padding * 2;
  const barGap = 4;
  const barW = (innerW - barGap * (quarters.length - 1)) / quarters.length;

  return (
    <svg width={width} height={height + 14} viewBox={`0 0 ${width} ${height + 14}`}>
      {/* Zero line */}
      <line
        x1={padding}
        y1={zeroY}
        x2={width - padding}
        y2={zeroY}
        stroke="rgb(100,116,139)"
        strokeOpacity={0.3}
        strokeWidth={1}
        strokeDasharray="2,2"
      />
      {quarters.map((q, i) => {
        const v = q.eps ?? 0;
        const est = q.estimate;
        const x = padding + i * (barW + barGap);
        const yTop =
          v >= 0 ? height - ((v - min) / range) * height : zeroY;
        const yBot =
          v >= 0 ? zeroY : height - ((v - min) / range) * height;
        const barH = Math.max(1, yBot - yTop);
        const fill = v >= 0 ? 'rgb(74,222,128)' : 'rgb(248,113,113)';
        const estY =
          est != null ? height - ((est - min) / range) * height : null;
        return (
          <g key={q.period_end + i}>
            <rect
              x={x}
              y={yTop}
              width={barW}
              height={barH}
              fill={fill}
              fillOpacity={0.75}
            >
              <title>
                {q.period_end}: EPS {v.toFixed(2)}
                {est != null ? ` (est ${est.toFixed(2)})` : ''}
              </title>
            </rect>
            {estY != null && (
              <line
                x1={x}
                y1={estY}
                x2={x + barW}
                y2={estY}
                stroke="rgb(148,163,184)"
                strokeWidth={1.4}
                strokeOpacity={0.8}
              />
            )}
            <text
              x={x + barW / 2}
              y={height + 11}
              textAnchor="middle"
              fontSize={9}
              fill="rgb(148,163,184)"
            >
              {q.period_end.slice(2, 7).replace('-', '/')}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Sparkline({ values, color, width = 64, height = 20 }: SparklineProps) {
  if (!values || values.length < 2) {
    return <span className="text-text-muted/50 text-[10px]">—</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = width / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={color}
      preserveAspectRatio="none"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function Squeeze() {
  const { result, loading, error, runScan, lookupSymbols } = useSqueeze();
  const {
    items: watchlistItems,
    add: addToWatchlist,
    remove: removeFromWatchlist,
    refresh: refreshWatchlist,
  } = useWatchlist();
  // Set of symbols already on the watchlist (stock-class — Squeeze is stocks-only).
  const watchedSymbols = new Set(
    watchlistItems
      .filter((it) => it.asset_type === 'stock')
      .map((it) => it.symbol),
  );
  const [daysBack, setDaysBack] = useState(7);
  const [tierFilter, setTierFilter] = useState<TierFilter>('ALL');
  const [extra, setExtra] = useState('');
  const [lookupHits, setLookupHits] = useState<
    { symbol: string; name: string }[]
  >([]);
  const [lookupOpen, setLookupOpen] = useState(false);
  const [lookupActive, setLookupActive] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  // Price ceiling — most squeeze setups are sub-$20. Null/0 disables the cap
  // so CVNA-shape rallies can still surface.
  const [maxPrice, setMaxPrice] = useState<number | null>(20);
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  // Auto-run once on first load. The hook's module-level cache makes this
  // a no-op on re-mount within ~10 minutes, so navigating away and back
  // doesn't trigger a fresh 10-15s scan.
  useEffect(() => {
    runScan({ daysBack: 7, fetchTechnical: true, maxPrice: 20 }).catch(
      () => {},
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced typeahead: when the user types a free-text query in the
  // extra-symbols box, look it up against /advisor/lookup so they can pick
  // by company name instead of memorising tickers.
  useEffect(() => {
    const q = extra.trim();
    // Treat short tokens or comma-separated lists as raw tickers — no lookup.
    if (q.length < 2 || q.includes(',')) {
      setLookupHits([]);
      setLookupOpen(false);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      const hits = await lookupSymbols(q, 6);
      if (cancelled) return;
      setLookupHits(hits.map((h) => ({ symbol: h.symbol, name: h.name })));
      setLookupOpen(hits.length > 0);
      setLookupActive(0);
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [extra, lookupSymbols]);

  const acceptLookup = (symbol: string) => {
    setExtra(symbol);
    setLookupOpen(false);
    setLookupHits([]);
  };

  const handleRun = () => {
    runScan({
      daysBack,
      extraSymbols: extra.trim() || undefined,
      fetchTechnical: true,
      maxResults: 50,
      maxPrice,
    }).catch(() => {});
  };

  const filteredResults: SqueezeResult[] = useMemo(() => {
    if (!result) return [];
    const filtered =
      tierFilter === 'ALL'
        ? [...result.results]
        : result.results.filter((r) => r.tier === tierFilter);

    const getValue = (r: SqueezeResult): number | string => {
      switch (sortKey) {
        case 'ticker':
          return r.ticker;
        case 'off_exchange_short_pct':
          return r.finra?.off_exchange_short_pct ?? -Infinity;
        case 'score':
          return r.score;
        case 'current_price':
          return r.current_price ?? -Infinity;
        case 'day_pct_change':
          return r.day_pct_change ?? -Infinity;
        case 'short_pct_of_float':
          return r.short_pct_of_float ?? -Infinity;
        case 'days_to_cover':
          return r.days_to_cover ?? -Infinity;
        case 'float_shares':
          return r.float_shares ?? Infinity; // smaller floats sort first by default
        case 'earnings_qoq_growth':
          return r.earnings_qoq_growth ?? -Infinity;
        case 'market_cap':
          return r.market_cap ?? -Infinity;
        case 'scanner_score':
          return r.scanner_score ?? -Infinity;
        default:
          return 0;
      }
    };

    filtered.sort((a, b) => {
      const va = getValue(a);
      const vb = getValue(b);
      let cmp: number;
      if (typeof va === 'string' && typeof vb === 'string') {
        cmp = va.localeCompare(vb);
      } else {
        cmp = (va as number) < (vb as number) ? -1 : (va as number) > (vb as number) ? 1 : 0;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return filtered;
  }, [result, tierFilter, sortKey, sortDir]);

  return (
    <Layout>
      <div className="px-4 sm:px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <div className="flex items-center gap-3">
            <Flame className="h-7 w-7 text-accent-cyan" />
            <h1 className="text-3xl font-bold tracking-tight text-text-primary">
              Squeeze Screener
            </h1>
          </div>
          <p className="mt-1 text-sm font-medium text-accent-cyan">
            7-factor · CAR/GME pattern · 13D filings + FINRA dark-pool short
            volume
          </p>
          {result?.finra_trade_date && (
            <p className="mt-1 text-xs text-text-muted">
              FINRA short-volume: {result.finra_trade_date} ·{' '}
              {result.filings_count} filings scanned ·{' '}
              {result.candidates_scored} candidates ·{' '}
              {result.passed_filters} passed structural filters
            </p>
          )}
        </motion.div>

        {/* Controls */}
        <div className="rounded-lg border border-border-subtle bg-bg-card p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleRun}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-accent-cyan px-4 py-2 text-sm font-semibold text-accent-foreground hover:bg-accent-cyan/90 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              {loading ? 'Scanning…' : 'Run Discovery'}
            </button>

            <div className="flex items-center gap-2">
              <label className="text-xs uppercase tracking-wider text-text-muted">
                Days Back
              </label>
              <input
                type="number"
                min={1}
                max={60}
                value={daysBack}
                onChange={(e) =>
                  setDaysBack(Math.max(1, Number(e.target.value) || 7))
                }
                className="w-16 rounded-md border border-border-subtle bg-bg-elevated px-2 py-1 text-sm font-mono text-text-primary focus:border-accent-cyan focus:outline-none"
              />
            </div>

            <div className="flex items-center gap-2">
              <label className="text-xs uppercase tracking-wider text-text-muted">
                Max $
              </label>
              <input
                type="number"
                min={0}
                step={5}
                value={maxPrice ?? 0}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setMaxPrice(v <= 0 ? null : v);
                }}
                placeholder="0 = no cap"
                className="w-20 rounded-md border border-border-subtle bg-bg-elevated px-2 py-1 text-sm font-mono text-text-primary focus:border-accent-cyan focus:outline-none"
                title="Price ceiling. 0 = no cap (CVNA-shape rallies). Defaults to $20 since most squeeze setups are sub-$20."
              />
              {maxPrice == null && (
                <span className="text-[10px] uppercase tracking-wider text-accent-cyan">
                  no cap
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 flex-1 min-w-[240px] relative">
              <Search className="h-4 w-4 text-text-muted" />
              <input
                type="text"
                placeholder="Ticker or company name (e.g. RXT or Rackspace)"
                value={extra}
                onChange={(e) => setExtra(e.target.value)}
                onBlur={() => setTimeout(() => setLookupOpen(false), 150)}
                onFocus={() => {
                  if (lookupHits.length > 0) setLookupOpen(true);
                }}
                className="flex-1 rounded-md border border-border-subtle bg-bg-elevated px-3 py-1.5 text-sm font-mono text-text-primary placeholder:text-text-muted/60 focus:border-accent-cyan focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === 'ArrowDown' && lookupOpen) {
                    e.preventDefault();
                    setLookupActive((i) =>
                      Math.min(i + 1, lookupHits.length - 1),
                    );
                  } else if (e.key === 'ArrowUp' && lookupOpen) {
                    e.preventDefault();
                    setLookupActive((i) => Math.max(i - 1, 0));
                  } else if (e.key === 'Enter') {
                    if (lookupOpen && lookupHits[lookupActive]) {
                      e.preventDefault();
                      acceptLookup(lookupHits[lookupActive].symbol);
                    } else {
                      handleRun();
                    }
                  } else if (e.key === 'Escape') {
                    setLookupOpen(false);
                  }
                }}
              />
              {lookupOpen && lookupHits.length > 0 && (
                <ul className="absolute left-6 right-0 top-full mt-1 z-20 max-h-72 overflow-y-auto rounded-md border border-border-subtle bg-bg-card shadow-lg">
                  {lookupHits.map((h, i) => (
                    <li
                      key={`${h.symbol}-${i}`}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        acceptLookup(h.symbol);
                      }}
                      onMouseEnter={() => setLookupActive(i)}
                      className={`flex items-center justify-between px-3 py-2 text-xs cursor-pointer transition-colors ${
                        i === lookupActive
                          ? 'bg-accent-cyan/10 text-text-primary'
                          : 'hover:bg-bg-elevated text-text-secondary'
                      }`}
                    >
                      <span className="font-mono font-semibold text-accent-cyan">
                        {h.symbol}
                      </span>
                      <span className="ml-3 truncate text-text-muted">
                        {h.name}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {result && (
              <button
                onClick={handleRun}
                className="inline-flex items-center gap-1.5 rounded-md border border-border-subtle px-3 py-1.5 text-xs text-text-secondary hover:border-accent-cyan hover:text-accent-cyan transition-colors"
                title="Re-scan with current filters"
              >
                <RefreshCw className="h-3 w-3" />
                Refresh
              </button>
            )}
          </div>

          {/* Tier filter chips */}
          <div className="flex items-center gap-2 text-xs">
            <span className="uppercase tracking-wider text-text-muted mr-1">
              Filter
            </span>
            {(['ALL', 'ADD', 'WATCHLIST', 'BASE'] as TierFilter[]).map((t) => (
              <button
                key={t}
                onClick={() => setTierFilter(t)}
                className={`rounded-md border px-3 py-1 transition-colors ${
                  tierFilter === t
                    ? 'border-accent-cyan text-accent-cyan bg-accent-cyan/10'
                    : 'border-border-subtle text-text-secondary hover:border-accent-cyan/50 hover:text-text-primary'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-danger-red/40 bg-danger-red/10 p-4 text-sm text-danger-red">
            <AlertTriangle className="inline h-4 w-4 mr-2" />
            {error}
          </div>
        )}

        {/* Caveats banner — once per scan */}
        {result?.data_caveats && result.data_caveats.length > 0 && (
          <details className="rounded-lg border border-border-subtle bg-bg-card p-3 text-xs text-text-muted">
            <summary className="cursor-pointer hover:text-text-primary uppercase tracking-wider">
              Data caveats ({result.data_caveats.length})
            </summary>
            <ul className="mt-2 space-y-1 pl-4 list-disc">
              {result.data_caveats.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </details>
        )}

        {/* Results table */}
        <div className="rounded-lg border border-border-subtle bg-bg-card overflow-hidden">
          {!result && !loading && (
            <div className="p-8 text-center text-text-muted text-sm">
              No scan yet — click <em>Run Discovery</em>.
            </div>
          )}
          {loading && !result && (
            <div className="p-8 text-center text-text-muted text-sm flex items-center justify-center gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-accent-cyan" />
              Pulling SEC + FINRA + yfinance + technical scores… can take 10-15s
            </div>
          )}
          {result && filteredResults.length === 0 && (
            <div className="p-8 text-center text-text-muted text-sm">
              No tickers in tier <em>{tierFilter}</em>. Try a different filter
              or widen <em>days back</em>.
            </div>
          )}
          {filteredResults.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-subtle text-left text-text-muted uppercase tracking-wider">
                    <SortHeader k="ticker" cur={sortKey} dir={sortDir} onClick={toggleSort} className="px-4 py-3">Ticker</SortHeader>
                    <SortHeader k="score" cur={sortKey} dir={sortDir} onClick={toggleSort}>Score</SortHeader>
                    <th className="px-2 py-3">Tier</th>
                    <SortHeader k="current_price" cur={sortKey} dir={sortDir} onClick={toggleSort}>Price</SortHeader>
                    <SortHeader k="day_pct_change" cur={sortKey} dir={sortDir} onClick={toggleSort}>Day %</SortHeader>
                    <th className="px-2 py-3">20d</th>
                    <SortHeader k="short_pct_of_float" cur={sortKey} dir={sortDir} onClick={toggleSort}>SI %</SortHeader>
                    <SortHeader k="days_to_cover" cur={sortKey} dir={sortDir} onClick={toggleSort}>DTC</SortHeader>
                    <SortHeader k="float_shares" cur={sortKey} dir={sortDir} onClick={toggleSort}>Float</SortHeader>
                    <SortHeader k="off_exchange_short_pct" cur={sortKey} dir={sortDir} onClick={toggleSort}>Off-Ex Short</SortHeader>
                    <SortHeader k="earnings_qoq_growth" cur={sortKey} dir={sortDir} onClick={toggleSort}>Earnings QoQ</SortHeader>
                    <SortHeader k="market_cap" cur={sortKey} dir={sortDir} onClick={toggleSort}>MC</SortHeader>
                    <th className="px-2 py-3">Sector</th>
                    <th className="px-2 py-3">13D</th>
                    <SortHeader k="scanner_score" cur={sortKey} dir={sortDir} onClick={toggleSort} className="px-2 py-3 text-right">Tech</SortHeader>
                  </tr>
                </thead>
                <tbody>
                  {filteredResults.map((r) => (
                    <RowGroup
                      key={r.ticker}
                      r={r}
                      expanded={expanded === r.ticker}
                      onToggle={() =>
                        setExpanded(expanded === r.ticker ? null : r.ticker)
                      }
                      isWatched={watchedSymbols.has(r.ticker)}
                      onAddWatch={async () => {
                        const note =
                          `${r.tier} · score ${r.score.toFixed(1)} · ` +
                          `SI ${((r.short_pct_of_float ?? 0) * 100).toFixed(0)}% · ` +
                          `float ${((r.float_shares ?? 0) / 1e6).toFixed(0)}M`;
                        try {
                          await addToWatchlist(r.ticker, 'stock', {
                            source: 'squeeze',
                            note,
                          });
                          // Belt-and-suspenders: useWatchlist's event bus
                          // should refresh items, but force it so the icon
                          // switches to "watched" immediately even if a
                          // race delays the bus.
                          await refreshWatchlist();
                          toast.success(`${r.ticker} added to watchlist`, {
                            description: note,
                          });
                        } catch (e) {
                          toast.error(`Could not add ${r.ticker}`, {
                            description:
                              e instanceof Error ? e.message : String(e),
                          });
                        }
                      }}
                      onRemoveWatch={async () => {
                        try {
                          await removeFromWatchlist(r.ticker, 'stock');
                          await refreshWatchlist();
                          toast.success(`${r.ticker} removed from watchlist`);
                        } catch (e) {
                          toast.error(`Could not remove ${r.ticker}`, {
                            description:
                              e instanceof Error ? e.message : String(e),
                          });
                        }
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}

interface RowGroupProps {
  r: SqueezeResult;
  expanded: boolean;
  onToggle: () => void;
  isWatched: boolean;
  onAddWatch: () => Promise<void> | void;
  onRemoveWatch: () => Promise<void> | void;
}

function RowGroup({
  r,
  expanded,
  onToggle,
  isWatched,
  onAddWatch,
  onRemoveWatch,
}: RowGroupProps) {
  const offEx = r.finra?.off_exchange_short_pct;
  const tierClass = TIER_STYLES[r.tier] || TIER_STYLES.BASE;

  return (
    <>
      <tr
        onClick={onToggle}
        className="border-b border-border-subtle/50 hover:bg-bg-elevated/40 cursor-pointer transition-colors"
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <div>
              <div className="font-bold text-accent-cyan text-sm">{r.ticker}</div>
              <div className="text-[10px] text-text-muted truncate max-w-[140px]">
                {r.name}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (isWatched) onRemoveWatch();
                else onAddWatch();
              }}
              title={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
              className={`rounded p-1 transition-colors ${
                isWatched
                  ? 'text-success-green hover:bg-success-green/10'
                  : 'text-text-muted hover:bg-accent-cyan/10 hover:text-accent-cyan'
              }`}
            >
              {isWatched ? (
                <Check className="h-3.5 w-3.5" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </td>
        <td className="px-2 py-3 text-sm font-mono font-bold tabular-nums">
          {r.score.toFixed(1)}
        </td>
        <td className="px-2 py-3">
          <span
            className={`inline-block rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider ${tierClass}`}
          >
            {r.tier}
          </span>
        </td>
        <td className="px-2 py-3 font-mono tabular-nums text-text-primary">
          {r.current_price != null ? `$${r.current_price.toFixed(2)}` : '—'}
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          {r.day_pct_change != null ? (
            <span
              className={
                r.day_pct_change > 0
                  ? 'text-success-green'
                  : r.day_pct_change < 0
                    ? 'text-danger-red'
                    : ''
              }
            >
              {r.day_pct_change > 0 ? '+' : ''}
              {(r.day_pct_change * 100).toFixed(1)}%
            </span>
          ) : (
            <span className="text-text-muted/50">—</span>
          )}
        </td>
        <td className="px-2 py-3">
          {r.sparkline && r.sparkline.length > 1 ? (
            <Sparkline
              values={r.sparkline}
              color={
                r.day_pct_change != null && r.day_pct_change >= 0
                  ? 'text-success-green'
                  : 'text-danger-red'
              }
            />
          ) : (
            <span className="text-text-muted/50 text-[10px]">—</span>
          )}
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          {fmtPct(r.short_pct_of_float, 1)}
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          {r.days_to_cover != null ? `${r.days_to_cover.toFixed(1)}d` : '—'}
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          {fmtShares(r.float_shares)}
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          <span
            className={
              offEx != null && offEx >= 50
                ? 'text-accent-cyan font-semibold'
                : offEx != null && offEx >= 40
                  ? 'text-accent-cyan/80'
                  : ''
            }
          >
            {fmtPctRaw(offEx, 1)}
          </span>
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          {/* When has_earnings_data is explicitly false, yfinance gave us
              nothing — render "—" even if the field happens to be 0.
              When the flag is missing (older API), fall back to null check. */}
          {r.has_earnings_data === false ||
          (r.has_earnings_data === undefined && r.earnings_qoq_growth == null) ? (
            <span className="text-text-muted/50" title="no earnings data">—</span>
          ) : r.earnings_qoq_growth != null ? (
            <span
              className={
                r.earnings_qoq_growth > 0.1
                  ? 'text-success-green'
                  : r.earnings_qoq_growth < -0.1
                    ? 'text-danger-red'
                    : ''
              }
            >
              {fmtPct(r.earnings_qoq_growth, 0)}
            </span>
          ) : (
            <span className="text-text-muted/50">—</span>
          )}
        </td>
        <td className="px-2 py-3 font-mono tabular-nums">
          {fmtMoney(r.market_cap)}
        </td>
        <td className="px-2 py-3 text-text-secondary">{r.sector || '—'}</td>
        <td className="px-2 py-3">
          {r.has_recent_13d_filing ? (
            <span className="text-success-green">●</span>
          ) : (
            <span className="text-text-muted/40">○</span>
          )}
        </td>
        <td className="px-2 py-3 text-right text-text-secondary font-mono tabular-nums">
          {r.scanner_score != null ? r.scanner_score.toFixed(0) : '—'}
        </td>
      </tr>
      {expanded && <ExpandedRow r={r} />}
    </>
  );
}

function ExpandedRow({ r }: { r: SqueezeResult }) {
  return (
    <tr className="border-b border-border-subtle bg-bg-elevated/40">
      <td colSpan={14} className="px-6 py-4 text-xs">
        {/* Quarterly EPS chart — full-width row, then 3-col detail grid below */}
        {r.quarterly_eps && r.quarterly_eps.length > 0 && (
          <div className="mb-4">
            <div className="text-text-muted mb-1 uppercase tracking-wider text-[10px]">
              Quarterly EPS{' '}
              <span className="text-text-muted/60 normal-case">
                (last {r.quarterly_eps.length} quarters · grey tick = est)
              </span>
            </div>
            <QuarterlyEarningsChart quarters={r.quarterly_eps} />
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Factor breakdown */}
          <div>
            <div className="text-text-muted mb-2 uppercase tracking-wider">
              Factor Breakdown
            </div>
            <div className="space-y-1">
              {(
                [
                  ['short_interest', 'Short Interest'],
                  ['float_size', 'Float Size'],
                  ['days_to_cover', 'Days to Cover'],
                  ['earnings_trend', 'Earnings Trend'],
                  ['recent_13d', '13D Filing'],
                  ['technical', 'Technical'],
                  ['off_exchange_short', 'Off-Ex Short'],
                ] as const
              ).map(([k, label]) => {
                const v = r.factors[k];
                const note = r.factor_notes[k];
                return (
                  <div
                    key={k}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="text-text-secondary">{label}</span>
                    <span className="text-text-primary font-mono tabular-nums">
                      {v.toFixed(2)}{' '}
                      <span className="text-text-muted">({note})</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* FINRA detail */}
          <div>
            <div className="text-text-muted mb-2 uppercase tracking-wider">
              FINRA Short Volume{' '}
              {r.finra?.trade_date && `(${r.finra.trade_date})`}
            </div>
            {r.finra ? (
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Short volume</span>
                  <span className="font-mono tabular-nums">
                    {fmtShares(r.finra.short_volume_total)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Total volume</span>
                  <span className="font-mono tabular-nums">
                    {fmtShares(r.finra.total_volume)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Short %</span>
                  <span className="font-mono tabular-nums">
                    {fmtPctRaw(r.finra.short_pct_total, 2)}
                  </span>
                </div>
                <div className="flex justify-between border-t border-border-subtle pt-1 mt-1">
                  <span className="text-text-secondary">Off-exchange short</span>
                  <span className="font-mono tabular-nums">
                    {fmtShares(r.finra.off_exchange_short_volume)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Off-ex %</span>
                  <span className="text-accent-cyan font-mono tabular-nums font-semibold">
                    {fmtPctRaw(r.finra.off_exchange_short_pct, 2)}
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-text-muted">No FINRA data for this date.</div>
            )}
          </div>

          {/* Filing + warnings */}
          <div>
            <div className="text-text-muted mb-2 uppercase tracking-wider">
              Filing &amp; Warnings
            </div>
            {r.filing ? (
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Form</span>
                  <span>{r.filing.form}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Filed</span>
                  <span className="font-mono tabular-nums">
                    {r.filing.filed_at}
                  </span>
                </div>
                <div className="text-text-primary">
                  By <span className="font-semibold">{r.filing.filer_name}</span>
                </div>
                <a
                  href={r.filing.edgar_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-accent-cyan hover:text-accent-cyan/80 mt-1"
                >
                  <ExternalLink className="h-3 w-3" />
                  Open on SEC.gov
                </a>
              </div>
            ) : (
              <div className="text-text-muted">No 13D in window.</div>
            )}
            {r.warnings.length > 0 && (
              <div className="mt-3 text-warning-amber/80">
                <div className="text-[10px] uppercase tracking-wider mb-1">
                  Warnings
                </div>
                <ul className="list-disc pl-4 space-y-0.5">
                  {r.warnings.map((w) => (
                    <li key={w}>{w.replace(/_/g, ' ')}</li>
                  ))}
                </ul>
              </div>
            )}
            {r.next_earnings_date && (
              <div className="mt-2 text-text-muted">
                Next earnings: {r.next_earnings_date}
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}
