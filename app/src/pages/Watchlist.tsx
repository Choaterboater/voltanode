import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import {
  Sparkles,
  Search,
  Plus,
  X,
  ArrowRight,
  ArrowUp,
  ArrowDown,
  Trash2,
  Flame,
  Eye,
  Zap,
  RefreshCw,
} from 'lucide-react';
import Layout from '@/components/Layout';
import {
  readEnrichedCache,
  useWatchlist,
  type EnrichedWatchlistItem,
} from '@/hooks/useWatchlist';

type SortKey =
  | 'symbol'
  | 'asset_type'
  | 'source'
  | 'added_at'
  | 'current_price'
  | 'day_pct_change'
  | 'week_pct_change'
  | 'relative_volume';

type SortDir = 'asc' | 'desc';

const SOURCE_BADGES: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }> }
> = {
  squeeze: { label: 'Squeeze', icon: Flame },
  scanner: { label: 'Scanner', icon: Zap },
  advisor: { label: 'Advisor', icon: Sparkles },
  manual: { label: 'Manual', icon: Eye },
};

function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return '—';
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(decimals)}%`;
}

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toExponential(2)}`;
}

interface SparklineProps {
  values: number[];
  color: string;
  width?: number;
  height?: number;
}

function Sparkline({ values, color, width = 64, height = 20 }: SparklineProps) {
  if (!values || values.length < 2) {
    return <span className="text-2xs text-text-muted/50">—</span>;
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
      className={`${className} stat-label cursor-pointer select-none bg-bg-input/50 transition-colors hover:text-text-primary`}
    >
      <div className="inline-flex items-center gap-1">
        <span className={active ? 'text-accent-cyan' : ''}>{children}</span>
        {active &&
          (dir === 'asc' ? (
            <ArrowUp className="h-3 w-3 text-accent-cyan" />
          ) : (
            <ArrowDown className="h-3 w-3 text-accent-cyan" />
          ))}
      </div>
    </th>
  );
}

export default function Watchlist() {
  const navigate = useNavigate();
  const { add, remove, fetchEnriched } = useWatchlist(false);

  // Hydrate from localStorage cache so the table never paints empty on
  // mount when the backend is wedged or restarting. Background fetch
  // overwrites with fresh data when it lands.
  const [items, setItems] = useState<EnrichedWatchlistItem[]>(() => {
    const cached = readEnrichedCache();
    return cached?.data ?? [];
  });
  const [cacheTs, setCacheTs] = useState<number | null>(() => {
    const cached = readEnrichedCache();
    return cached?.ts ?? null;
  });
  // freshTs marks when the most recent live fetch succeeded. While it's
  // null but `items` is populated, we're showing cached data — surface
  // that in the UI so the operator knows.
  const [freshTs, setFreshTs] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<'all' | 'crypto' | 'stock'>('all');
  const [query, setQuery] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const [newAssetType, setNewAssetType] = useState<'stock' | 'crypto'>('stock');
  const [sortKey, setSortKey] = useState<SortKey>('added_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const reload = async (opts?: { nocache?: boolean }) => {
    setLoading(true);
    setError(null);
    try {
      const enriched = await fetchEnriched(undefined, opts);
      setItems(enriched);
      const now = Date.now();
      setFreshTs(now);
      setCacheTs(now);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Mount-time fetch — if it lands, freshTs becomes set and the "cached"
    // ribbon goes away. If it fails, the cached items stay visible.
    reload();
    // Refetch on window focus + tab visibility — covers "came back to the
    // tab and want fresh data" without polling continuously.
    const onFocus = () => {
      reload();
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') reload();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(k);
      setSortDir(k === 'symbol' ? 'asc' : 'desc');
    }
  };

  const filtered = useMemo(() => {
    let list = items;
    if (tab !== 'all') list = list.filter((it) => it.asset_type === tab);
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(
        (it) =>
          it.symbol.toLowerCase().includes(q) ||
          (it.note ?? '').toLowerCase().includes(q),
      );
    }
    const sorted = [...list];
    const get = (it: EnrichedWatchlistItem): string | number => {
      switch (sortKey) {
        case 'symbol':
          return it.symbol;
        case 'asset_type':
          return it.asset_type;
        case 'source':
          return it.source;
        case 'added_at':
          return it.added_at;
        case 'current_price':
          return it.current_price ?? -Infinity;
        case 'day_pct_change':
          return it.day_pct_change ?? -Infinity;
        case 'week_pct_change':
          return it.week_pct_change ?? -Infinity;
        case 'relative_volume':
          return it.relative_volume ?? -Infinity;
      }
    };
    sorted.sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      let cmp: number;
      if (typeof va === 'string' && typeof vb === 'string') {
        cmp = va.localeCompare(vb);
      } else {
        cmp = (va as number) < (vb as number) ? -1 : (va as number) > (vb as number) ? 1 : 0;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }, [items, tab, query, sortKey, sortDir]);

  const counts = useMemo(() => {
    let crypto = 0,
      stock = 0;
    for (const it of items) {
      if (it.asset_type === 'crypto') crypto++;
      else if (it.asset_type === 'stock') stock++;
    }
    return { all: items.length, crypto, stock };
  }, [items]);

  const handleAddCustom = async () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    try {
      await add(sym, newAssetType, { source: 'manual' });
      setNewSymbol('');
      setShowAdd(false);
      await reload();
    } catch {
      /* ignore */
    }
  };

  const handleRemove = async (it: EnrichedWatchlistItem) => {
    await remove(it.symbol, it.asset_type);
    await reload();
  };

  const handleAnalyze = (sym: string, type: 'stock' | 'crypto') => {
    navigate('/advisor', { state: { symbol: sym, assetType: type } });
  };

  return (
    <Layout>
      <div className="px-4 sm:px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="flex items-center gap-3">
            <Eye className="h-6 w-6 text-accent-cyan" />
            <h1 className="text-2xl font-bold tracking-tight text-text-primary">Watchlist</h1>
          </div>
          <p className="mt-1 text-sm text-text-muted">
            Symbols you've flagged across the app — manual adds plus picks
            promoted from Squeeze and Scanner. Live price, day change, and
            sparkline pulled per row.
          </p>
          {/* Cached-data ribbon — when items are on screen but freshTs is
              still null, we're rendering localStorage cache because the
              live fetch hasn't landed (or failed). Tells the operator
              not to trust prices/sparklines as live yet. Auto-hides once
              fresh data arrives. */}
          {items.length > 0 && !freshTs && cacheTs && (
            <p className="pill-warning mt-2">
              <RefreshCw className="h-3 w-3" />
              Cached ·{' '}
              {(() => {
                const sec = Math.max(1, Math.round((Date.now() - cacheTs) / 1000));
                if (sec < 60) return `${sec}s ago`;
                const min = Math.round(sec / 60);
                if (min < 60) return `${min}m ago`;
                const hr = Math.round(min / 60);
                return `${hr}h ago`;
              })()}
            </p>
          )}
        </motion.div>

        {/* Controls */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="panel p-4 space-y-3"
        >
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
              {(['all', 'stock', 'crypto'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    tab === t
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {t === 'all' ? 'All' : t === 'stock' ? 'Stocks' : 'Crypto'}
                  <span className="ml-1.5 font-mono text-2xs tabular-nums text-text-muted">
                    {t === 'all'
                      ? counts.all
                      : t === 'stock'
                        ? counts.stock
                        : counts.crypto}
                  </span>
                </button>
              ))}
            </div>

            <div className="relative flex-1 min-w-[180px]">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                placeholder="Filter symbol or note…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full rounded-lg border border-border-subtle bg-bg-input py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              />
            </div>

            <button
              onClick={() => reload({ nocache: true })}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-bg-elevated/60 px-3.5 py-2 text-xs font-medium text-text-secondary transition-colors hover:border-accent-cyan/30 hover:text-text-primary disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>

            <button
              onClick={() => setShowAdd(!showAdd)}
              className="inline-flex items-center gap-1 rounded-lg bg-accent-cyan px-3.5 py-2 text-xs font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90"
            >
              <Plus className="h-3.5 w-3.5" />
              Add
            </button>
          </div>

          {showAdd && (
            <div className="flex items-center gap-2">
              <select
                value={newAssetType}
                onChange={(e) =>
                  setNewAssetType(e.target.value as 'stock' | 'crypto')
                }
                className="rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              >
                <option value="stock">Stock</option>
                <option value="crypto">Crypto</option>
              </select>
              <input
                type="text"
                placeholder="Ticker (e.g. RXT or BTC)"
                value={newSymbol}
                onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                onKeyDown={(e) => e.key === 'Enter' && handleAddCustom()}
                className="flex-1 rounded-lg border border-border-subtle bg-bg-input px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              />
              <button
                onClick={handleAddCustom}
                className="rounded-lg bg-accent-cyan px-3.5 py-2 text-xs font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90"
              >
                Add
              </button>
              <button
                onClick={() => {
                  setShowAdd(false);
                  setNewSymbol('');
                }}
                className="rounded-lg border border-border-subtle bg-bg-elevated/60 px-3.5 py-2 text-xs font-medium text-text-secondary transition-colors hover:border-accent-cyan/30 hover:text-text-primary"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </motion.div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-danger-red/40 bg-danger-red/10 p-3 text-sm text-danger-red">
            {error}
          </div>
        )}

        {/* Table */}
        <div className="panel overflow-hidden">
          {loading && items.length === 0 && (
            <div className="p-8 text-center text-text-muted text-sm">
              Loading watchlist + live data…
            </div>
          )}
          {!loading && items.length === 0 && (
            <div className="p-10 flex flex-col items-center justify-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-cyan/10">
                <Eye className="h-6 w-6 text-accent-cyan" />
              </div>
              <p className="text-base font-semibold text-text-primary">
                Your watchlist is empty
              </p>
              <p className="text-xs text-text-muted text-center max-w-md">
                Track tickers across the app — the Advisor, Squeeze screener, and
                Scanner can all promote picks here. Or seed it now with a one-click suggestion.
              </p>
              <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
                {[
                  { sym: 'BTC', type: 'crypto' as const },
                  { sym: 'ETH', type: 'crypto' as const },
                  { sym: 'AAPL', type: 'stock' as const },
                  { sym: 'NVDA', type: 'stock' as const },
                  { sym: 'SPY', type: 'stock' as const },
                ].map(({ sym, type }) => (
                  <button
                    key={sym}
                    onClick={async () => {
                      try {
                        await add(sym, type, { source: 'manual' });
                        await reload();
                      } catch {
                        /* ignore */
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-bg-elevated px-3 py-1 text-xs font-mono text-text-primary hover:border-accent-cyan hover:text-accent-cyan transition-colors"
                  >
                    <Plus className="h-3 w-3" /> {sym}
                  </button>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-3 text-xs text-text-muted">
                <button
                  onClick={() => navigate('/squeeze')}
                  className="inline-flex items-center gap-1 text-accent-cyan hover:underline"
                >
                  <Flame className="h-3 w-3" /> Open Squeeze
                </button>
                <span aria-hidden>·</span>
                <button
                  onClick={() => navigate('/advisor')}
                  className="inline-flex items-center gap-1 text-accent-cyan hover:underline"
                >
                  <Sparkles className="h-3 w-3" /> Open Advisor
                </button>
              </div>
            </div>
          )}
          {filtered.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <SortHeader k="symbol" cur={sortKey} dir={sortDir} onClick={toggleSort} className="px-4 py-3">
                      Ticker
                    </SortHeader>
                    <SortHeader k="source" cur={sortKey} dir={sortDir} onClick={toggleSort}>
                      Source
                    </SortHeader>
                    <SortHeader k="current_price" cur={sortKey} dir={sortDir} onClick={toggleSort}>
                      Price
                    </SortHeader>
                    <SortHeader k="day_pct_change" cur={sortKey} dir={sortDir} onClick={toggleSort}>
                      Day %
                    </SortHeader>
                    <SortHeader k="week_pct_change" cur={sortKey} dir={sortDir} onClick={toggleSort}>
                      Week %
                    </SortHeader>
                    <th className="stat-label bg-bg-input/50 px-2 py-3">20d</th>
                    <SortHeader k="relative_volume" cur={sortKey} dir={sortDir} onClick={toggleSort}>
                      Rel Vol
                    </SortHeader>
                    <SortHeader k="added_at" cur={sortKey} dir={sortDir} onClick={toggleSort}>
                      Added
                    </SortHeader>
                    <th className="stat-label bg-bg-input/50 px-2 py-3">Note</th>
                    <th className="stat-label bg-bg-input/50 px-2 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((it) => {
                    const meta = SOURCE_BADGES[it.source] || SOURCE_BADGES.manual;
                    const Icon = meta.icon;
                    return (
                      <tr
                        key={`${it.symbol}-${it.asset_type}`}
                        className="border-b border-border-subtle/60 hover:bg-bg-elevated/40 transition-colors"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-semibold text-accent-cyan">
                              {it.symbol}
                            </span>
                            <span
                              className={`inline-block rounded border px-1 py-0.5 text-2xs uppercase tracking-wider ${
                                it.asset_type === 'crypto'
                                  ? 'border-accent-cyan/30 text-accent-cyan/80'
                                  : 'border-border-subtle text-text-muted'
                              }`}
                            >
                              {it.asset_type}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-3">
                          <span className="pill-neutral">
                            <Icon className="h-2.5 w-2.5" />
                            {meta.label}
                          </span>
                        </td>
                        <td className="px-2 py-3 font-mono text-xs tabular-nums text-text-primary">
                          {fmtPrice(it.current_price)}
                        </td>
                        <td className="px-2 py-3 font-mono text-xs tabular-nums">
                          {it.day_pct_change != null ? (
                            <span
                              className={
                                it.day_pct_change > 0
                                  ? 'text-success-green'
                                  : it.day_pct_change < 0
                                    ? 'text-danger-red'
                                    : ''
                              }
                            >
                              {fmtPct(it.day_pct_change)}
                            </span>
                          ) : (
                            <span className="text-text-muted/50">—</span>
                          )}
                        </td>
                        <td className="px-2 py-3 font-mono text-xs tabular-nums">
                          {it.week_pct_change != null ? (
                            <span
                              className={
                                it.week_pct_change > 0
                                  ? 'text-success-green'
                                  : it.week_pct_change < 0
                                    ? 'text-danger-red'
                                    : ''
                              }
                            >
                              {fmtPct(it.week_pct_change)}
                            </span>
                          ) : (
                            <span className="text-text-muted/50">—</span>
                          )}
                        </td>
                        <td className="px-2 py-3">
                          {it.sparkline && it.sparkline.length > 1 ? (
                            <Sparkline
                              values={it.sparkline}
                              color={
                                (it.day_pct_change ?? 0) >= 0
                                  ? 'text-success-green'
                                  : 'text-danger-red'
                              }
                            />
                          ) : (
                            <span className="text-text-muted/50">—</span>
                          )}
                        </td>
                        <td className="px-2 py-3 font-mono text-xs tabular-nums">
                          {it.relative_volume != null ? (
                            <span
                              className={
                                it.relative_volume >= 2
                                  ? 'text-accent-cyan font-semibold'
                                  : it.relative_volume >= 1.5
                                    ? 'text-accent-cyan/80'
                                    : ''
                              }
                            >
                              {it.relative_volume.toFixed(1)}×
                            </span>
                          ) : (
                            <span className="text-text-muted/50">—</span>
                          )}
                        </td>
                        <td className="px-2 py-3 font-mono text-xs tabular-nums text-text-muted whitespace-nowrap">
                          {new Date(it.added_at).toLocaleDateString()}
                        </td>
                        <td className="px-2 py-3 max-w-[220px]">
                          <span
                            className="block truncate text-xs text-text-muted"
                            title={it.note ?? ''}
                          >
                            {it.note ?? '—'}
                          </span>
                        </td>
                        <td className="px-2 py-3 text-right whitespace-nowrap">
                          <button
                            onClick={() =>
                              handleAnalyze(it.symbol, it.asset_type)
                            }
                            title="Analyze in Advisor"
                            className="inline-flex items-center gap-0.5 rounded-md p-1.5 text-text-muted hover:bg-accent-cyan/10 hover:text-accent-cyan transition-colors"
                          >
                            <Sparkles className="h-3.5 w-3.5" />
                            <ArrowRight className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => handleRemove(it)}
                            title="Remove from watchlist"
                            className="rounded-md p-1.5 text-text-muted hover:bg-danger-red/10 hover:text-danger-red transition-colors"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
