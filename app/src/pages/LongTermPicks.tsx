import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import {
  Anchor,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  ArrowRight,
  AlertCircle,
} from 'lucide-react';
import Layout from '@/components/Layout';
import { getLongTermPicks, type LongTermPick, type LongTermResponse } from '@/lib/api';

function fmtPrice(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toExponential(2)}`;
}

// Inline horizontal score bar 0–1, color-shaded by value.
function ScoreBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color =
    value >= 0.7
      ? 'bg-success-green'
      : value >= 0.4
        ? 'bg-accent-cyan'
        : value >= 0.2
          ? 'bg-warning-amber'
          : 'bg-danger-red';
  return (
    <div className="flex items-center gap-1.5">
      <div className="relative h-1.5 w-12 overflow-hidden rounded-full bg-bg-elevated">
        <div
          className={`absolute inset-y-0 left-0 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-2xs tabular-nums text-text-muted">
        {value.toFixed(2)}
      </span>
      {label && <span className="text-2xs text-text-muted/70">{label}</span>}
    </div>
  );
}

export default function LongTermPicks() {
  const navigate = useNavigate();

  const [assetClass, setAssetClass] = useState<'stock' | 'crypto'>('stock');
  const [sector, setSector] = useState('');
  const [symbolsInput, setSymbolsInput] = useState('');
  const [topN, setTopN] = useState(25);
  const [minScore, setMinScore] = useState(0);
  // Default universe limit is bumped to 250 so a capped scan (e.g. <$50)
  // has enough candidates to surface meaningful picks. The full S&P 500
  // is 503 names — 250 covers half alphabetically and still finishes in
  // ~30-60s.
  const [limitUniverse, setLimitUniverse] = useState(100);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [wFund, setWFund] = useState(0.5);
  const [wTrend, setWTrend] = useState(0.3);
  const [wVol, setWVol] = useState(0.2);

  // Budget cap — operator picks a max share price so cheaper names surface.
  // null = no cap. Quick chips for the common breakpoints + custom input.
  const [maxPrice, setMaxPrice] = useState<number | null>(null);

  const [data, setData] = useState<LongTermResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getLongTermPicks({
        asset_class: assetClass,
        top: topN,
        min_score: minScore,
        limit_universe: limitUniverse,
        symbols: symbolsInput.trim() || undefined,
        sector: sector.trim() || undefined,
        weight_fundamentals: wFund,
        weight_trend: wTrend,
        weight_low_volatility: wVol,
        max_price: maxPrice ?? undefined,
      });
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // Run an initial scan against a small fast universe so the page isn't
  // empty on first load. Full S&P 500 takes 2-5 minutes — that's a button
  // click, not the default.
  useEffect(() => {
    setSymbolsInput('AAPL,MSFT,NVDA,GOOGL,JNJ,KO,PG,WMT,COST,UNH');
    // run after state lands
    setTimeout(() => {
      void runScan();
    }, 50);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Layout>
      <div className="px-4 sm:px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-5">
        {/* Header */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <div className="flex items-center gap-3">
            <Anchor className="h-6 w-6 text-accent-cyan" />
            <h1 className="text-2xl font-bold tracking-tight text-text-primary">Long-Term Picks</h1>
          </div>
          <p className="mt-1 text-sm text-text-muted max-w-3xl">
            Year-plus holding candidates ranked by{' '}
            <span className="font-mono text-text-secondary">fundamentals (50%) + trend (30%) + low volatility (20%)</span>.
            Defaults scan a custom 10-name sample for speed — clear the Symbols box
            and click Scan to run the full S&amp;P 500 (2–5 min). Crypto ranks on
            trend + vol only since traditional fundamentals don't apply.
          </p>
        </motion.div>

        {/* Controls */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="panel space-y-3 p-5"
        >
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
              {(['stock', 'crypto'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setAssetClass(t)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    assetClass === t
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {t === 'stock' ? 'Stocks' : 'Crypto'}
                </button>
              ))}
            </div>

            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                placeholder="Symbols (comma-separated) — leave blank for S&P 500"
                value={symbolsInput}
                onChange={(e) => setSymbolsInput(e.target.value.toUpperCase())}
                className="w-full rounded-lg border border-border-subtle bg-bg-input py-2 pl-8 pr-3 font-mono text-xs text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              />
            </div>

            <input
              type="text"
              placeholder="Sector filter"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="w-32 rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
            />

            <button
              onClick={() => void runScan()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-cyan px-3.5 py-2 text-xs font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {loading ? 'Scanning…' : 'Scan'}
            </button>

            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              {showAdvanced ? 'Hide' : 'Advanced'}
            </button>
          </div>

          {/* Budget cap — chips for the common breakpoints + custom. The
              chip's `null` value means "no cap" (default). Clicking a cap
              clears the preloaded symbols list and auto-runs a fresh scan
              against the full universe, because the most common reason
              someone picks <$50 is to find cheap S&P names — not to
              intersect with the page's preloaded 10 mega-caps. */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="stat-label">
              Max price
            </span>
            {[
              { label: 'Any', val: null },
              { label: '< $25', val: 25 },
              { label: '< $50', val: 50 },
              { label: '< $100', val: 100 },
              { label: '< $250', val: 250 },
            ].map(({ label, val }) => {
              const active = maxPrice === val;
              return (
                <button
                  key={label}
                  onClick={() => {
                    setMaxPrice(val);
                    // Clear preloaded symbols so the cap scans the full
                    // universe. If the user typed their own list, also
                    // clear — common case is "give me cheap picks", not
                    // "filter MY list". They can paste symbols back if
                    // they really wanted both.
                    if (val !== null) {
                      setSymbolsInput('');
                      // Auto-run so the operator doesn't have to click
                      // Scan separately — the chip click IS the intent.
                      setTimeout(() => void runScan(), 50);
                    }
                  }}
                  className={`rounded-full border px-2.5 py-0.5 font-mono text-2xs transition-colors ${
                    active
                      ? 'border-accent-cyan bg-accent-cyan/15 text-accent-cyan'
                      : 'border-border-subtle bg-bg-input text-text-secondary hover:border-accent-cyan/40 hover:text-accent-cyan'
                  }`}
                >
                  {label}
                </button>
              );
            })}
            <input
              type="number"
              min="0"
              step="5"
              placeholder="custom"
              value={
                maxPrice !== null && ![25, 50, 100, 250].includes(maxPrice)
                  ? maxPrice
                  : ''
              }
              onChange={(e) => {
                const v = e.target.value;
                setMaxPrice(v === '' ? null : Number(v));
              }}
              className="w-20 rounded-lg border border-border-subtle bg-bg-input px-2 py-0.5 font-mono text-2xs text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
            />
          </div>

          {showAdvanced && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pt-2 border-t border-border-subtle">
              <label className="text-xs text-text-muted space-y-1">
                <span>Top N: <span className="font-mono tabular-nums text-text-primary">{topN}</span></span>
                <input
                  type="range" min="5" max="100" step="5"
                  value={topN}
                  onChange={(e) => setTopN(Number(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-xs text-text-muted space-y-1">
                <span>Min score: <span className="font-mono tabular-nums text-text-primary">{minScore}</span></span>
                <input
                  type="range" min="0" max="100" step="5"
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-xs text-text-muted space-y-1">
                <span>Universe limit: <span className="font-mono tabular-nums text-text-primary">{limitUniverse}</span></span>
                <input
                  type="range" min="20" max="500" step="20"
                  value={limitUniverse}
                  onChange={(e) => setLimitUniverse(Number(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-xs text-text-muted space-y-1">
                <span>Weight: fundamentals <span className="font-mono tabular-nums text-text-primary">{wFund.toFixed(2)}</span></span>
                <input
                  type="range" min="0" max="1" step="0.05"
                  value={wFund}
                  onChange={(e) => setWFund(Number(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-xs text-text-muted space-y-1">
                <span>Weight: trend <span className="font-mono tabular-nums text-text-primary">{wTrend.toFixed(2)}</span></span>
                <input
                  type="range" min="0" max="1" step="0.05"
                  value={wTrend}
                  onChange={(e) => setWTrend(Number(e.target.value))}
                  className="w-full"
                />
              </label>
              <label className="text-xs text-text-muted space-y-1">
                <span>Weight: low-vol <span className="font-mono tabular-nums text-text-primary">{wVol.toFixed(2)}</span></span>
                <input
                  type="range" min="0" max="1" step="0.05"
                  value={wVol}
                  onChange={(e) => setWVol(Number(e.target.value))}
                  className="w-full"
                />
              </label>
            </div>
          )}
        </motion.div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-danger-red/40 bg-danger-red/10 p-3 text-sm text-danger-red">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Meta strip */}
        {data && !error && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-2xs text-text-muted">
            <span>Universe: <span className="font-mono tabular-nums text-text-secondary">{data.universe_size}</span></span>
            <span>Scored: <span className="font-mono tabular-nums text-text-secondary">{data.scored}</span></span>
            <span>Elapsed: <span className="font-mono tabular-nums text-text-secondary">{data.elapsed_ms}ms</span></span>
            <span>
              Weights: <span className="font-mono tabular-nums text-text-secondary">
                fund={data.weights.fundamentals?.toFixed(2)} ·
                trend={data.weights.trend?.toFixed(2)} ·
                vol={data.weights.low_volatility?.toFixed(2)}
              </span>
            </span>
            {data.failed.length > 0 && (
              <span className="text-warning-amber">
                {data.failed.length} failed (see devtools console for symbols)
              </span>
            )}
          </div>
        )}

        {/* Table */}
        <div className="panel overflow-hidden">
          {loading && !data && (
            <div className="p-8 text-center text-text-muted text-sm">
              Scanning… fundamentals + 2y OHLCV per symbol. Full S&amp;P takes a few minutes.
            </div>
          )}
          {!loading && data && data.results.length === 0 && (
            <div className="p-10 text-center text-text-muted text-sm space-y-2">
              {maxPrice !== null && symbolsInput.trim() ? (
                <>
                  <p>No picks under ${maxPrice} in your custom symbol list.</p>
                  <button
                    onClick={() => {
                      setSymbolsInput('');
                      setTimeout(() => void runScan(), 50);
                    }}
                    className="text-accent-cyan hover:underline"
                  >
                    Clear symbols and scan the full S&amp;P 500
                  </button>
                </>
              ) : maxPrice !== null ? (
                <>
                  <p>No picks under ${maxPrice} in the first {limitUniverse} symbols.</p>
                  <p className="text-2xs">
                    Try bumping the universe limit (Advanced) or raising the price cap.
                  </p>
                </>
              ) : (
                <p>No picks above min-score threshold. Lower the threshold or expand the universe.</p>
              )}
            </div>
          )}
          {data && data.results.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-subtle text-left text-2xs font-medium uppercase tracking-wider text-text-muted">
                    <th className="px-3 py-3">#</th>
                    <th className="px-2 py-3">Symbol</th>
                    <th className="px-2 py-3 hidden md:table-cell">Name</th>
                    <th className="px-2 py-3 hidden lg:table-cell">Sector</th>
                    <th className="px-2 py-3">Score</th>
                    <th className="px-2 py-3">Fund</th>
                    <th className="px-2 py-3">Trend</th>
                    <th className="px-2 py-3">Low-Vol</th>
                    <th className="px-2 py-3">Price</th>
                    <th className="px-2 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((r: LongTermPick, i: number) => (
                    <tr
                      key={r.symbol}
                      className="border-b border-border-subtle/50 hover:bg-bg-elevated/40 transition-colors"
                    >
                      <td className="px-3 py-3 font-mono tabular-nums text-text-muted">{i + 1}</td>
                      <td className="px-2 py-3">
                        <div className="font-mono font-bold text-accent-cyan text-sm">{r.symbol}</div>
                      </td>
                      <td className="px-2 py-3 hidden md:table-cell text-text-secondary max-w-[200px] truncate" title={r.name}>
                        {r.name || '—'}
                      </td>
                      <td className="px-2 py-3 hidden lg:table-cell text-text-muted">
                        {r.sector || '—'}
                      </td>
                      <td className="px-2 py-3 font-mono tabular-nums">
                        <span
                          className={
                            r.score >= 80
                              ? 'text-success-green font-semibold'
                              : r.score >= 60
                                ? 'text-accent-cyan'
                                : r.score >= 40
                                  ? 'text-text-primary'
                                  : 'text-text-muted'
                          }
                        >
                          {r.score.toFixed(1)}
                        </span>
                      </td>
                      <td className="px-2 py-3">
                        <ScoreBar value={r.components.fundamentals?.score ?? 0} />
                      </td>
                      <td className="px-2 py-3">
                        <ScoreBar value={r.components.trend?.score ?? 0} />
                      </td>
                      <td className="px-2 py-3">
                        <ScoreBar value={r.components.low_volatility?.score ?? 0} />
                      </td>
                      <td className="px-2 py-3 font-mono tabular-nums text-text-primary">
                        {fmtPrice(r.current_price)}
                      </td>
                      <td className="px-2 py-3 text-right whitespace-nowrap">
                        <button
                          onClick={() =>
                            navigate('/advisor', {
                              state: { symbol: r.symbol, assetType: assetClass },
                            })
                          }
                          title="Deep-dive in Advisor"
                          className="inline-flex items-center gap-0.5 rounded p-1.5 text-accent-cyan hover:bg-accent-cyan/10 transition-colors"
                        >
                          <Sparkles className="h-3.5 w-3.5" />
                          <ArrowRight className="h-3 w-3" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="mx-auto max-w-2xl text-center text-2xs text-text-muted/70">
          Not market timing. These are "worth buying and forgetting about" candidates.
          Drill into any pick via the Advisor button for the LLM-driven deep dive
          (macro, insider activity, earnings, sentiment, fundamentals narrative).
        </p>
      </div>
    </Layout>
  );
}
