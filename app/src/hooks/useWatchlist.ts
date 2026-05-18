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

// localStorage cache so the watchlist doesn't show empty when the backend
// is temporarily wedged or the page mounts mid-restart. We snapshot every
// successful fetch and hydrate from the snapshot on mount; the background
// fetch then overwrites with fresh data when it lands.
//
// Two keys (plain items + enriched items) because some pages only need
// the cheap symbol set (Squeeze for "is watched?"), others need prices.
const CACHE_KEY_ITEMS = 'volta:watchlist:items:v1';
const CACHE_KEY_ENRICHED = 'volta:watchlist:enriched:v1';

interface CacheEnvelope<T> {
  ts: number;          // epoch ms
  data: T;
}

function _cacheRead<T>(key: string): CacheEnvelope<T> | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const env = JSON.parse(raw) as CacheEnvelope<T>;
    if (!env || typeof env.ts !== 'number') return null;
    return env;
  } catch {
    return null;
  }
}

function _cacheWrite<T>(key: string, data: T): void {
  try {
    localStorage.setItem(
      key,
      JSON.stringify({ ts: Date.now(), data } satisfies CacheEnvelope<T>),
    );
  } catch {
    /* quota / private mode / etc — non-fatal */
  }
}

// Public cache helpers — the Watchlist page uses these for the enriched
// flavor too. Returning null when the cache is empty rather than throwing
// so callers can branch cleanly.
export function readWatchlistCache(): CacheEnvelope<WatchlistItem[]> | null {
  return _cacheRead<WatchlistItem[]>(CACHE_KEY_ITEMS);
}
export function writeWatchlistCache(items: WatchlistItem[]): void {
  _cacheWrite(CACHE_KEY_ITEMS, items);
}
export function readEnrichedCache(): CacheEnvelope<EnrichedWatchlistItem[]> | null {
  return _cacheRead<EnrichedWatchlistItem[]>(CACHE_KEY_ENRICHED);
}
export function writeEnrichedCache(items: EnrichedWatchlistItem[]): void {
  _cacheWrite(CACHE_KEY_ENRICHED, items);
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
  // Hydrate state from the localStorage cache so the page never paints
  // empty when the backend is wedged or restarting. The background fetch
  // overwrites this with fresh data when it lands.
  const [items, setItems] = useState<WatchlistItem[]>(() => {
    const cached = readWatchlistCache();
    return cached?.data ?? [];
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchTs, setLastFetchTs] = useState<number | null>(() => {
    const cached = readWatchlistCache();
    return cached?.ts ?? null;
  });

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/watchlist/`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as WatchlistItem[];
      setItems(data);
      setLastFetchTs(Date.now());
      writeWatchlistCache(data);
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
      const items = (d.items ?? []) as EnrichedWatchlistItem[];
      // Cache the enriched payload so the Watchlist page can hydrate
      // instantly on next mount, even if the backend is wedged.
      writeEnrichedCache(items);
      return items;
    },
    [],
  );

  return {
    items,
    loading,
    error,
    refresh,
    add,
    remove,
    contains,
    fetchEnriched,
    lastFetchTs,
  };
}
