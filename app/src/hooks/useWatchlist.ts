import { useCallback, useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export interface WatchlistItem {
  symbol: string;
  asset_type: 'stock' | 'crypto';
  note: string | null;
  source: string; // "manual" | "squeeze" | "scanner" | "advisor"
  added_at: string;
}

export interface EnrichedWatchlistItem extends WatchlistItem {
  current_price: number | null;
  day_pct_change: number | null;
  week_pct_change: number | null;
  sparkline: number[] | null;
  relative_volume: number | null;
  fetch_error: string | null;
}

// Module-level event bus so cross-page mutations refresh automatically
// (e.g. when the Squeeze page adds an item, the Watchlist page sees it).
const _listeners = new Set<() => void>();
function _emitChange() {
  for (const fn of _listeners) {
    try {
      fn();
    } catch {
      /* swallow */
    }
  }
}

export function useWatchlist(autoload = true) {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/watchlist/`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as WatchlistItem[];
      setItems(data);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const add = useCallback(
    async (
      symbol: string,
      asset_type: 'stock' | 'crypto' = 'stock',
      opts: { note?: string; source?: string } = {},
    ) => {
      const r = await fetch(`${API_BASE}/watchlist/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          asset_type,
          note: opts.note ?? null,
          source: opts.source ?? 'manual',
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      _emitChange();
      return data;
    },
    [],
  );

  const remove = useCallback(
    async (symbol: string, asset_type: 'stock' | 'crypto' = 'stock') => {
      const r = await fetch(
        `${API_BASE}/watchlist/${encodeURIComponent(symbol)}?asset_type=${asset_type}`,
        { method: 'DELETE' },
      );
      if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
      _emitChange();
      return r.ok;
    },
    [],
  );

  const contains = useCallback(
    async (symbol: string, asset_type: 'stock' | 'crypto' = 'stock'): Promise<boolean> => {
      try {
        const r = await fetch(
          `${API_BASE}/watchlist/contains/${encodeURIComponent(symbol)}?asset_type=${asset_type}`,
        );
        if (!r.ok) return false;
        const d = await r.json();
        return !!d.in_watchlist;
      } catch {
        return false;
      }
    },
    [],
  );

  // Initial load + cross-page sync
  useEffect(() => {
    if (!autoload) return;
    refresh().catch(() => {});
    const handler = () => {
      refresh().catch(() => {});
    };
    _listeners.add(handler);
    return () => {
      _listeners.delete(handler);
    };
  }, [autoload, refresh]);

  /**
   * Fetch watchlist items with live price + day_pct + sparkline attached.
   * Used by the Watchlist page table view.
   */
  const fetchEnriched = useCallback(
    async (
      filterAssetType?: 'stock' | 'crypto',
      opts?: { nocache?: boolean },
    ): Promise<EnrichedWatchlistItem[]> => {
      const params = new URLSearchParams();
      if (filterAssetType) params.set('asset_type', filterAssetType);
      if (opts?.nocache) params.set('nocache', 'true');
      const qs = params.toString();
      const url = `${API_BASE}/watchlist/enriched${qs ? `?${qs}` : ''}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      return (d.items ?? []) as EnrichedWatchlistItem[];
    },
    [],
  );

  return { items, loading, error, refresh, add, remove, contains, fetchEnriched };
}
