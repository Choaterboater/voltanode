import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  Loader2,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Zap,
  AlertCircle,
  ChevronRight,
} from 'lucide-react';
import Layout from '@/components/Layout';
import {
  getNewsImpact,
  getNewsVelocity,
  type ImpactBucket,
  type ImpactReport,
  type VelocitySnapshot,
} from '@/lib/api';

// Velocity-label → color/icon mapping. Keeps the chip styling consistent
// with the codebase's accent/success/danger tokens.
const VELOCITY_STYLES: Record<string, { cls: string; Icon: typeof TrendingUp; label: string }> = {
  accelerating_bull: {
    cls: 'border-success-green/50 bg-success-green/10 text-success-green',
    Icon: TrendingUp,
    label: 'accelerating bull',
  },
  drifting_bull: {
    cls: 'border-accent-cyan/40 bg-accent-cyan/10 text-accent-cyan',
    Icon: TrendingUp,
    label: 'drifting bull',
  },
  flat: {
    cls: 'border-border-subtle bg-bg-elevated text-text-muted',
    Icon: Activity,
    label: 'flat',
  },
  drifting_bear: {
    cls: 'border-warning-amber/40 bg-warning-amber/10 text-warning-amber',
    Icon: TrendingDown,
    label: 'drifting bear',
  },
  accelerating_bear: {
    cls: 'border-danger-red/50 bg-danger-red/10 text-danger-red',
    Icon: TrendingDown,
    label: 'accelerating bear',
  },
};

function fmtPct(n: number | null | undefined, sign = false, decimals = 2): string {
  if (n == null || !isFinite(n)) return '—';
  const formatted = `${n.toFixed(decimals)}%`;
  return sign && n >= 0 ? `+${formatted}` : formatted;
}

const DEFAULT_SYMBOLS = ['NVDA', 'AAPL', 'TSLA', 'MSFT', 'GOOGL', 'AMZN', 'META'];

export default function NewsAnalytics() {
  // Velocity panel state
  const [velSymbols, setVelSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [velMap, setVelMap] = useState<Record<string, VelocitySnapshot | null>>({});
  const [velLoading, setVelLoading] = useState(false);

  // Impact backtest state
  const [impactSymbols, setImpactSymbols] = useState('NVDA,AAPL,TSLA');
  const [lookbackDays, setLookbackDays] = useState(30);
  const [horizons, setHorizons] = useState('1,3,5');
  const [impact, setImpact] = useState<ImpactReport | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactError, setImpactError] = useState<string | null>(null);

  const loadVelocity = async () => {
    setVelLoading(true);
    const next: Record<string, VelocitySnapshot | null> = {};
    await Promise.allSettled(
      velSymbols.map(async (s) => {
        try {
          next[s] = await getNewsVelocity(s);
        } catch {
          next[s] = null;
        }
      })
    );
    setVelMap(next);
    setVelLoading(false);
  };

  const loadImpact = async () => {
    setImpactLoading(true);
    setImpactError(null);
    try {
      const r = await getNewsImpact({
        symbols: impactSymbols,
        lookback_days: lookbackDays,
        horizons,
      });
      setImpact(r);
    } catch (e) {
      setImpactError(e instanceof Error ? e.message : String(e));
    } finally {
      setImpactLoading(false);
    }
  };

  useEffect(() => {
    loadVelocity();
    // Auto-run the velocity panel on mount; impact backtest is a deliberate
    // "click to run" because it hits yfinance and can take 5-30s.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sort velocity rows: accelerating bull/bear first, flat last
  const sortedVel = useMemo(() => {
    const order: Record<string, number> = {
      accelerating_bull: 0,
      accelerating_bear: 1,
      drifting_bull: 2,
      drifting_bear: 3,
      flat: 4,
    };
    return [...velSymbols].sort((a, b) => {
      const va = velMap[a]?.velocity_label ?? 'flat';
      const vb = velMap[b]?.velocity_label ?? 'flat';
      const oa = order[va] ?? 5;
      const ob = order[vb] ?? 5;
      if (oa !== ob) return oa - ob;
      // Within same label, sort by |velocity| desc
      const ma = Math.abs(velMap[a]?.velocity ?? 0);
      const mb = Math.abs(velMap[b]?.velocity ?? 0);
      return mb - ma;
    });
  }, [velSymbols, velMap]);

  // Pivot impact buckets by score-bucket for easier table rendering
  const impactByBucket = useMemo(() => {
    if (!impact?.buckets) return [];
    type Row = {
      key: string;
      score_low: number;
      score_high: number;
      cells: Record<number, ImpactBucket>;
    };
    const map = new Map<string, Row>();
    for (const b of impact.buckets) {
      const key = `${b.score_low}_${b.score_high}`;
      if (!map.has(key)) {
        map.set(key, {
          key,
          score_low: b.score_low,
          score_high: b.score_high,
          cells: {},
        });
      }
      map.get(key)!.cells[b.horizon_days] = b;
    }
    return Array.from(map.values()).sort((a, b) => a.score_low - b.score_low);
  }, [impact]);

  const horizonsList = useMemo(() => {
    if (!impact?.buckets || impact.buckets.length === 0) {
      return horizons.split(',').map((h) => parseInt(h.trim(), 10)).filter(Boolean);
    }
    const set = new Set(impact.buckets.map((b) => b.horizon_days));
    return Array.from(set).sort((a, b) => a - b);
  }, [impact, horizons]);

  return (
    <Layout>
      <div className="px-4 sm:px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <div className="flex items-center gap-3">
            <Zap className="h-6 w-6 text-accent-cyan" />
            <h1 className="text-2xl font-bold text-text-primary">News Analytics</h1>
          </div>
          <p className="mt-1 text-sm text-text-muted max-w-3xl">
            Sentiment velocity (how fast news is changing per symbol) and impact-calibration backtest
            (did historical scores actually predict price moves?). Velocity loads on mount; the
            calibration backtest runs on demand because it hits yfinance per symbol.
          </p>
        </motion.div>

        {/* Velocity panel */}
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="rounded-[10px] border border-border-subtle bg-bg-card p-4 space-y-3"
        >
          <div className="flex items-center justify-between flex-wrap gap-3">
            <h2 className="text-base font-semibold text-text-primary inline-flex items-center gap-2">
              <Activity className="h-4 w-4 text-accent-cyan" />
              Velocity (1h vs 24h)
            </h2>
            <button
              onClick={loadVelocity}
              disabled={velLoading}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-subtle bg-bg-elevated px-3 py-1.5 text-xs text-text-secondary hover:border-accent-cyan hover:text-accent-cyan transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${velLoading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
          <div className="text-[11px] text-text-muted">
            <span className="font-mono text-text-secondary">velocity</span> = short-window avg compound minus long-window avg.
            Positive means news is becoming <em>more</em> positive recently. <span className="font-mono text-text-secondary">acceleration</span> is the
            change-of-change between adjacent windows — sniffs a regime shift.
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-subtle text-left text-text-muted uppercase tracking-wider">
                  <th className="px-3 py-2.5">Symbol</th>
                  <th className="px-2 py-2.5">Label</th>
                  <th className="px-2 py-2.5 text-right">Velocity</th>
                  <th className="px-2 py-2.5 text-right">Accel</th>
                  <th className="px-2 py-2.5 text-right">1h avg</th>
                  <th className="px-2 py-2.5 text-right">6h avg</th>
                  <th className="px-2 py-2.5 text-right">24h avg</th>
                  <th className="px-2 py-2.5 text-right">Fresh %</th>
                  <th className="px-2 py-2.5 text-right">24h n</th>
                </tr>
              </thead>
              <tbody>
                {sortedVel.map((sym) => {
                  const v = velMap[sym];
                  const style = VELOCITY_STYLES[v?.velocity_label ?? 'flat'] ?? VELOCITY_STYLES.flat;
                  const Icon = style.Icon;
                  const w1 = v?.windows.find((w) => w.hours === 1);
                  const w6 = v?.windows.find((w) => w.hours === 6);
                  const w24 = v?.windows.find((w) => w.hours === 24);
                  return (
                    <tr key={sym} className="border-b border-border-subtle/50 hover:bg-bg-elevated/40">
                      <td className="px-3 py-2 font-mono font-bold text-accent-cyan">{sym}</td>
                      <td className="px-2 py-2">
                        <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${style.cls}`}>
                          <Icon className="h-2.5 w-2.5" />
                          {style.label}
                        </span>
                      </td>
                      <td className={`px-2 py-2 text-right font-mono tabular-nums ${(v?.velocity ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
                        {v ? `${v.velocity >= 0 ? '+' : ''}${v.velocity.toFixed(3)}` : '—'}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-text-secondary">
                        {v ? `${v.acceleration >= 0 ? '+' : ''}${v.acceleration.toFixed(3)}` : '—'}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-text-secondary">
                        {w1 ? `${w1.avg_compound >= 0 ? '+' : ''}${w1.avg_compound.toFixed(3)}` : '—'}
                        <span className="text-text-muted/70 ml-1">({w1?.article_count ?? 0})</span>
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-text-secondary">
                        {w6 ? `${w6.avg_compound >= 0 ? '+' : ''}${w6.avg_compound.toFixed(3)}` : '—'}
                        <span className="text-text-muted/70 ml-1">({w6?.article_count ?? 0})</span>
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-text-secondary">
                        {w24 ? `${w24.avg_compound >= 0 ? '+' : ''}${w24.avg_compound.toFixed(3)}` : '—'}
                        <span className="text-text-muted/70 ml-1">({w24?.article_count ?? 0})</span>
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-text-muted">
                        {v ? `${(v.fresh_article_pct * 100).toFixed(0)}%` : '—'}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-text-muted">
                        {w24?.article_count ?? 0}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </motion.section>

        {/* Impact calibration backtest */}
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="rounded-[10px] border border-border-subtle bg-bg-card p-4 space-y-3"
        >
          <div className="flex items-center justify-between flex-wrap gap-3">
            <h2 className="text-base font-semibold text-text-primary inline-flex items-center gap-2">
              <ChevronRight className="h-4 w-4 text-accent-cyan" />
              Impact calibration — do scores predict returns?
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <input
              type="text"
              value={impactSymbols}
              onChange={(e) => setImpactSymbols(e.target.value.toUpperCase())}
              placeholder="NVDA,AAPL,TSLA"
              className="flex-1 min-w-[200px] rounded-md border border-border-subtle bg-bg-elevated py-1.5 px-3 text-xs font-mono text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
            />
            <label className="text-[10px] text-text-muted inline-flex items-center gap-1.5">
              Lookback
              <select
                value={lookbackDays}
                onChange={(e) => setLookbackDays(Number(e.target.value))}
                className="rounded-md border border-border-subtle bg-bg-elevated py-1 px-2 text-xs text-text-primary focus:border-accent-cyan focus:outline-none"
              >
                <option value={7}>7d</option>
                <option value={14}>14d</option>
                <option value={30}>30d</option>
                <option value={60}>60d</option>
                <option value={90}>90d</option>
              </select>
            </label>
            <label className="text-[10px] text-text-muted inline-flex items-center gap-1.5">
              Horizons
              <input
                type="text"
                value={horizons}
                onChange={(e) => setHorizons(e.target.value)}
                placeholder="1,3,5"
                className="w-20 rounded-md border border-border-subtle bg-bg-elevated py-1 px-2 text-xs font-mono text-text-primary focus:border-accent-cyan focus:outline-none"
              />
            </label>
            <button
              onClick={loadImpact}
              disabled={impactLoading || !impactSymbols.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-accent-foreground hover:bg-accent-cyan/90 disabled:opacity-50"
            >
              {impactLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              {impactLoading ? 'Scanning…' : 'Run backtest'}
            </button>
          </div>

          {impactError && (
            <div className="flex items-center gap-2 rounded-lg border border-danger-red/40 bg-danger-red/10 p-3 text-sm text-danger-red">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {impactError}
            </div>
          )}

          {impact && !impactError && (
            <>
              <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-text-muted">
                <span>articles: <span className="font-mono text-text-secondary">{impact.article_count}</span></span>
                <span>skipped: <span className="font-mono text-text-secondary">{impact.skipped_count}</span></span>
                <span>symbols: <span className="font-mono text-text-secondary">{impact.symbols.join(',')}</span></span>
                <span>window: <span className="font-mono text-text-secondary">{impact.lookback_days}d</span></span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-subtle text-left text-text-muted uppercase tracking-wider">
                      <th className="px-3 py-2.5">Score bucket</th>
                      {horizonsList.map((h) => (
                        <th key={`mean-${h}`} colSpan={3} className="px-2 py-2.5 text-center border-l border-border-subtle/50">
                          {h}-day horizon
                        </th>
                      ))}
                    </tr>
                    <tr className="border-b border-border-subtle text-left text-text-muted uppercase tracking-wider text-[9px]">
                      <th className="px-3 py-1.5"></th>
                      {horizonsList.flatMap((h) => [
                        <th key={`n-${h}`} className="px-1 py-1.5 text-right border-l border-border-subtle/50">n</th>,
                        <th key={`mean-${h}`} className="px-1 py-1.5 text-right">mean</th>,
                        <th key={`hit-${h}`} className="px-1 py-1.5 text-right">hit%</th>,
                      ])}
                    </tr>
                  </thead>
                  <tbody>
                    {impactByBucket.map((row) => {
                      const isStrongNeg = row.score_low < -0.4;
                      const isStrongPos = row.score_high > 0.4 && row.score_low >= 0;
                      const rowHl = isStrongNeg
                        ? 'bg-danger-red/5'
                        : isStrongPos
                          ? 'bg-success-green/5'
                          : '';
                      return (
                        <tr key={row.key} className={`border-b border-border-subtle/50 ${rowHl}`}>
                          <td className="px-3 py-2 font-mono tabular-nums text-text-primary">
                            [{row.score_low >= 0 ? '+' : ''}{row.score_low.toFixed(2)}, {row.score_high >= 0 ? '+' : ''}{row.score_high.toFixed(2)})
                          </td>
                          {horizonsList.flatMap((h) => {
                            const c = row.cells[h];
                            if (!c) return [
                              <td key={`n-${h}`} className="px-1 py-2 text-right text-text-muted/40 border-l border-border-subtle/50">—</td>,
                              <td key={`mean-${h}`} className="px-1 py-2 text-right text-text-muted/40">—</td>,
                              <td key={`hit-${h}`} className="px-1 py-2 text-right text-text-muted/40">—</td>,
                            ];
                            const meanCls = c.mean_return_pct > 0 ? 'text-success-green' : c.mean_return_pct < 0 ? 'text-danger-red' : 'text-text-muted';
                            // Hit-rate is meaningful for directional buckets; the middle [-0.1,+0.1) bucket
                            // always reports 0.5 (undefined) — dim it so the operator doesn't over-read.
                            const isMid = row.score_low < 0 && row.score_high > 0;
                            const hitCls = isMid
                              ? 'text-text-muted/50'
                              : c.hit_rate >= 0.7
                                ? 'text-success-green font-semibold'
                                : c.hit_rate >= 0.5
                                  ? 'text-text-primary'
                                  : 'text-danger-red';
                            return [
                              <td key={`n-${h}`} className="px-1 py-2 text-right font-mono tabular-nums text-text-muted border-l border-border-subtle/50">
                                {c.n}
                              </td>,
                              <td key={`mean-${h}`} className={`px-1 py-2 text-right font-mono tabular-nums ${meanCls}`}>
                                {fmtPct(c.mean_return_pct, true, 2)}
                              </td>,
                              <td key={`hit-${h}`} className={`px-1 py-2 text-right font-mono tabular-nums ${hitCls}`}>
                                {(c.hit_rate * 100).toFixed(0)}%
                              </td>,
                            ];
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <p className="text-[10px] text-text-muted/70 max-w-3xl">
                Hit-rate is directional: positive-score buckets hit when forward return is positive; negative-score buckets hit when forward return is negative.
                The middle <span className="font-mono">[-0.10, +0.10)</span> bucket straddles zero so its hit-rate is reported as 50% (undefined). Strong-conviction
                rows are tinted for emphasis.
              </p>
            </>
          )}
        </motion.section>
      </div>
    </Layout>
  );
}
