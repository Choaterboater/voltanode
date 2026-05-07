import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import {
  Sparkles,
  Search,
  Plus,
  X,
  ArrowRight,
  Trash2,
  Flame,
  Eye,
  Zap,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';
import { useWatchlist, type WatchlistItem } from '@/hooks/useWatchlist';

const SOURCE_BADGES: Record<
  string,
  { label: string; className: string; icon: React.ComponentType<{ className?: string }> }
> = {
  squeeze: {
    label: 'Squeeze',
    className: 'bg-accent-cyan/15 text-accent-cyan border-accent-cyan/40',
    icon: Flame,
  },
  scanner: {
    label: 'Scanner',
    className: 'bg-success-green/15 text-success-green border-success-green/40',
    icon: Zap,
  },
  advisor: {
    label: 'Advisor',
    className: 'bg-warning-amber/15 text-warning-amber border-warning-amber/40',
    icon: Sparkles,
  },
  manual: {
    label: 'Manual',
    className: 'bg-bg-elevated text-text-muted border-border-subtle',
    icon: Eye,
  },
};

export default function Watchlist() {
  const navigate = useNavigate();
  const { items, loading, refresh, add, remove } = useWatchlist();
  const [tab, setTab] = useState<'all' | 'crypto' | 'stock'>('all');
  const [query, setQuery] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const [newAssetType, setNewAssetType] = useState<'stock' | 'crypto'>('stock');

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
    return list;
  }, [items, tab, query]);

  const handleAnalyze = (symbol: string, asset_type: 'stock' | 'crypto') => {
    navigate('/advisor', { state: { symbol, assetType: asset_type } });
  };

  const handleAddCustom = async () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    try {
      await add(sym, newAssetType, { source: 'manual' });
      setNewSymbol('');
      setShowAdd(false);
      refresh().catch(() => {});
    } catch {
      /* errors surfaced via the hook */
    }
  };

  const handleRemove = async (it: WatchlistItem) => {
    await remove(it.symbol, it.asset_type);
    refresh().catch(() => {});
  };

  const counts = useMemo(() => {
    let crypto = 0;
    let stock = 0;
    for (const it of items) {
      if (it.asset_type === 'crypto') crypto++;
      else if (it.asset_type === 'stock') stock++;
    }
    return { all: items.length, crypto, stock };
  }, [items]);

  return (
    <Layout title="Watchlist">
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h2 className="text-xl font-bold text-text-primary">Watchlist</h2>
          <p className="mt-1 text-sm text-text-muted">
            Symbols you've flagged across the app — manual adds plus picks
            promoted from the Squeeze and Scanner pages.
          </p>
        </motion.div>

        {/* Tabs + Search + Add */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-1 rounded-md bg-bg-input border border-border-subtle p-0.5">
              {(['all', 'stock', 'crypto'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                    tab === t
                      ? 'bg-bg-elevated text-accent-cyan'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  {t === 'all' ? 'All' : t === 'stock' ? 'Stocks' : 'Crypto'}
                  <span className="ml-1.5 text-[10px] text-text-muted">
                    {t === 'all' ? counts.all : t === 'stock' ? counts.stock : counts.crypto}
                  </span>
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-text-muted" />
                <input
                  type="text"
                  placeholder="Filter..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="w-40 rounded-md border border-border-subtle bg-bg-input py-1.5 pl-8 pr-3 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
                />
              </div>
              <button
                onClick={() => setShowAdd(!showAdd)}
                className="inline-flex items-center gap-1 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
              >
                <Plus className="h-3.5 w-3.5" />
                Add
              </button>
            </div>
          </div>

          {/* Add custom */}
          {showAdd && (
            <div className="mt-3 flex items-center gap-2">
              <select
                value={newAssetType}
                onChange={(e) => setNewAssetType(e.target.value as 'stock' | 'crypto')}
                className="rounded-md border border-border-subtle bg-bg-input py-1.5 px-2 text-xs text-text-primary focus:border-accent-cyan focus:outline-none"
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
                className="flex-1 rounded-md border border-border-subtle bg-bg-input py-1.5 px-3 text-xs font-mono text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
              <button
                onClick={handleAddCustom}
                className="rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
              >
                Add
              </button>
              <button
                onClick={() => {
                  setShowAdd(false);
                  setNewSymbol('');
                }}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-bg-elevated transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </motion.div>

        {/* Empty / loading states */}
        {loading && items.length === 0 && (
          <div className="flex h-48 flex-col items-center justify-center rounded-[10px] border border-border-subtle bg-bg-surface text-text-muted text-sm">
            Loading watchlist…
          </div>
        )}

        {!loading && items.length === 0 && (
          <div className="flex h-48 flex-col items-center justify-center rounded-[10px] border border-border-subtle bg-bg-surface gap-2">
            <Eye className="h-7 w-7 text-text-muted" />
            <p className="text-sm text-text-primary">Your watchlist is empty</p>
            <p className="text-xs text-text-muted text-center max-w-xs">
              Add symbols manually with the <strong>Add</strong> button, or promote
              picks from the <strong>Squeeze</strong> screener.
            </p>
          </div>
        )}

        {/* Grid */}
        {filtered.length > 0 && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {filtered.map((it, idx) => {
              const meta = SOURCE_BADGES[it.source] || SOURCE_BADGES.manual;
              const Icon = meta.icon;
              return (
                <motion.div
                  key={`${it.symbol}-${it.asset_type}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.03 }}
                  className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-mono text-sm font-semibold text-accent-cyan">
                          {it.symbol}
                        </h3>
                        <Badge variant={it.asset_type === 'crypto' ? 'cyan' : 'info'}>
                          {it.asset_type}
                        </Badge>
                        <span
                          className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${meta.className}`}
                        >
                          <Icon className="h-2.5 w-2.5" />
                          {meta.label}
                        </span>
                      </div>
                      {it.note && (
                        <p className="mt-1 text-xs text-text-muted leading-snug truncate">
                          {it.note}
                        </p>
                      )}
                      <p className="mt-1 text-[10px] text-text-muted">
                        Added {new Date(it.added_at).toLocaleDateString()}
                      </p>
                    </div>
                    <button
                      onClick={() => handleRemove(it)}
                      title="Remove from watchlist"
                      className="rounded-md p-1.5 text-text-muted hover:bg-danger-red/10 hover:text-danger-red transition-colors"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div className="mt-3 flex items-center justify-end">
                    <button
                      onClick={() => handleAnalyze(it.symbol, it.asset_type)}
                      className="inline-flex items-center gap-1 rounded-md bg-accent-cyan/10 px-3 py-1.5 text-xs font-medium text-accent-cyan hover:bg-accent-cyan/20 transition-colors"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      Analyze
                      <ArrowRight className="h-3 w-3" />
                    </button>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}

        {items.length > 0 && filtered.length === 0 && (
          <div className="flex h-32 flex-col items-center justify-center rounded-[10px] border border-border-subtle bg-bg-surface text-sm text-text-muted">
            No items match your filter.
          </div>
        )}
      </div>
    </Layout>
  );
}
