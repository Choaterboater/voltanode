import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLocation } from 'react-router';
import {
  Search,
  Loader2,
  TrendingUp,
  TrendingDown,
  Minus,
  Target,
  Shield,
  Zap,
  Activity,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import Layout from '@/components/Layout';
import { useAdvisor, lookupSymbol, type IndicatorReading, type PriceTarget, type LLMCommentary, type SymbolLookupHit } from '@/hooks/useAdvisor';
import { useWatchlist } from '@/hooks/useWatchlist';
import { Brain } from 'lucide-react';
import { toast } from 'sonner';

type TimeRange = '30d' | '90d' | '365d';

const timeRanges: { key: TimeRange; label: string }[] = [
  { key: '30d', label: '1mo' },
  { key: '90d', label: '3mo' },
  { key: '365d', label: '1yr' },
];

const quickSelectCrypto = ['BTC', 'ETH', 'SOL', 'BNB'];
const quickSelectStocks = ['AAPL', 'TSLA', 'NVDA', 'MSFT'];

// ── Helpers ──

function verdictColor(verdict: string): string {
  const v = verdict.toLowerCase();
  if (v.includes('strong_buy')) return 'text-success-green';
  if (v.includes('buy')) return 'text-success-green';
  if (v.includes('strong_sell')) return 'text-danger-red';
  if (v.includes('sell')) return 'text-danger-red';
  return 'text-text-secondary';
}

function verdictBg(verdict: string): string {
  const v = verdict.toLowerCase();
  if (v.includes('buy')) return 'bg-success-green';
  if (v.includes('sell')) return 'bg-danger-red';
  return 'bg-text-muted';
}

function verdictIcon(verdict: string) {
  const v = verdict.toLowerCase();
  if (v.includes('buy')) return <TrendingUp className="h-6 w-6" />;
  if (v.includes('sell')) return <TrendingDown className="h-6 w-6" />;
  return <Minus className="h-6 w-6" />;
}

function signalPill(signal: string): string {
  if (signal === 'bullish') return 'pill-success';
  if (signal === 'bearish') return 'pill-danger';
  return 'pill-warning';
}

function formatCurrency(v: number) {
  if (v >= 1000) return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `$${v.toFixed(4)}`;
}

function timeHorizonLabel(h: string) {
  // Labels mirror the lookback-range buttons (1mo / 3mo / 1yr) so the
  // displayed horizon always matches what the user actually selected.
  if (h === 'short_term') return 'Short Term (1 month)';
  if (h === 'medium_term') return 'Medium Term (3 months)';
  return 'Long Term (1 year)';
}

function rangeToDays(range: TimeRange): number {
  if (range === '30d') return 30;
  if (range === '90d') return 90;
  return 365;
}

// ── Indicator Card ──
function IndicatorCard({ reading }: { reading: IndicatorReading }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <motion.div
      layout
      className="panel panel-hover cursor-pointer p-3"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={signalPill(reading.signal)}>
            {reading.signal.charAt(0).toUpperCase() + reading.signal.slice(1)}
          </span>
          <span className="text-sm font-medium text-text-primary">{reading.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 rounded-full bg-bg-input overflow-hidden">
            <div
              className={`h-full rounded-full ${reading.signal === 'bullish' ? 'bg-success-green' : reading.signal === 'bearish' ? 'bg-danger-red' : 'bg-warning-amber'}`}
              style={{ width: `${reading.strength * 100}%` }}
            />
          </div>
          {expanded ? <ChevronUp className="h-3.5 w-3.5 text-text-muted" /> : <ChevronDown className="h-3.5 w-3.5 text-text-muted" />}
        </div>
      </div>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <p className="mt-2 text-xs text-text-secondary">{reading.description}</p>
            <p className="mt-1 font-mono text-xs tabular-nums text-text-muted">Value: {reading.value}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Price Target Card ──
function PriceTargetCard({ target, currentPrice }: { target: PriceTarget; currentPrice: number }) {
  const isAbove = target.price > currentPrice;
  const pct = Math.abs((target.price - currentPrice) / currentPrice * 100);
  return (
    <div className="panel flex items-center justify-between p-3">
      <div>
        <p className="text-xs font-medium text-text-primary">{target.label}</p>
        <p className="text-xs text-text-muted mt-0.5">{target.rationale}</p>
      </div>
      <div className="text-right">
        <p className={`font-mono text-sm font-medium tabular-nums ${isAbove ? 'text-success-green' : 'text-danger-red'}`}>
          {formatCurrency(target.price)}
        </p>
        <p className="font-mono text-xs tabular-nums text-text-muted">{isAbove ? '+' : '-'}{pct.toFixed(1)}%</p>
        <div className="mt-1 h-1 w-20 rounded-full bg-bg-input overflow-hidden ml-auto">
          <div className="h-full rounded-full bg-accent-cyan" style={{ width: `${target.probability * 100}%` }} />
        </div>
      </div>
    </div>
  );
}

// ── Chart Component ──
function PriceChart({ chartData }: { chartData: { timestamps: string[]; close: number[]; sma_20?: (number | null)[]; sma_50?: (number | null)[]; ema_20?: (number | null)[]; ema_50?: (number | null)[]; bb_upper?: (number | null)[]; bb_lower?: (number | null)[] } }) {
  const data = chartData.timestamps.map((t, i) => ({
    date: t.slice(5, 10),
    close: chartData.close[i],
    sma20: chartData.sma_20?.[i] ?? null,
    sma50: chartData.sma_50?.[i] ?? null,
    ema20: chartData.ema_20?.[i] ?? null,
    ema50: chartData.ema_50?.[i] ?? null,
    bbUpper: chartData.bb_upper?.[i] ?? null,
    bbLower: chartData.bb_lower?.[i] ?? null,
  }));

  return (
    <div className="h-[320px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(34,211,238,0.25)" />
              <stop offset="100%" stopColor="rgba(34,211,238,0)" />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1C2840" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: '#6E7E96' }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#6E7E96' }}
            axisLine={false}
            tickLine={false}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => `$${v < 1 ? v.toFixed(4) : v.toFixed(0)}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0D1424',
              border: '1px solid #1C2840',
              borderRadius: 12,
              fontSize: 12,
            }}
            labelStyle={{ color: '#A8B7CC' }}
            itemStyle={{ color: '#F2F6FC' }}
            formatter={(value: number, name: string) => {
              const labels: Record<string, string> = {
                close: 'Close',
                sma20: 'SMA 20',
                sma50: 'SMA 50',
                ema20: 'EMA 20',
                ema50: 'EMA 50',
                bbUpper: 'BB Upper',
                bbLower: 'BB Lower',
              };
              return [typeof value === 'number' ? `$${value.toFixed(4)}` : '-', labels[name] || name];
            }}
          />
          <Area type="monotone" dataKey="close" stroke="#22D3EE" strokeWidth={2} fill="url(#priceGradient)" dot={false} />
          <Line type="monotone" dataKey="sma20" stroke="#34D399" strokeWidth={1} dot={false} strokeDasharray="4 4" />
          <Line type="monotone" dataKey="sma50" stroke="#A78BFA" strokeWidth={1} dot={false} strokeDasharray="4 4" />
          {chartData.bb_upper && <Line type="monotone" dataKey="bbUpper" stroke="#F87171" strokeWidth={1} dot={false} strokeOpacity={0.5} />}
          {chartData.bb_lower && <Line type="monotone" dataKey="bbLower" stroke="#F87171" strokeWidth={1} dot={false} strokeOpacity={0.5} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Research Report (Multi-Dimensional) Card ──
function ResearchReportCard({ report }: { report: import('@/hooks/useAdvisor').ResearchReport }) {
  const dimColor = (label: string) =>
    label.includes('NEGATIVE') ? 'text-danger-red'
    : label.includes('POSITIVE') ? 'text-success-green'
    : 'text-warning-amber';
  const verdictColor = (label: string) =>
    label.includes('STRONG_BUY') || label === 'BUY' ? 'text-success-green'
    : label.includes('SELL') ? 'text-danger-red'
    : 'text-warning-amber';

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.05 }}
      className="panel border-accent-cyan/30 p-5"
    >
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border-subtle pb-3">
        <div>
          <p className="stat-label text-accent-cyan">
            Research Report{report.llm_model && ` · ${report.llm_model}`}
          </p>
          <h3 className="mt-1 text-2xl font-bold tracking-tight text-text-primary">
            Should I Buy or Sell {report.symbol}?
          </h3>
        </div>
        <div className="text-right">
          <p className={`text-2xl font-bold tracking-tight ${verdictColor(report.overall_label)}`}>
            {report.overall_label.replace('_', ' ')}
          </p>
          <p className="text-xs text-text-muted">
            <span className="font-mono tabular-nums">{report.confidence}%</span> confidence · {report.optimal_timeframe}
          </p>
        </div>
      </div>

      {/* Three dimensions */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[report.fundamental, report.technical, report.sentiment].map((dim) => {
          // When data_available is explicitly false, the score is a
          // default-50 fallback that means "no data" — render dimmed +
          // strikethrough on the score + "NO DATA" label so the
          // composite isn't read as "actually neutral fundamentals".
          const noData = dim.data_available === false;
          return (
            <div
              key={dim.name}
              className={`rounded-lg border border-border-subtle bg-bg-input/40 p-3 ${noData ? 'opacity-60' : ''}`}
            >
              <div className="flex items-baseline justify-between">
                <span className="stat-label">{dim.name}</span>
                <span className="font-mono text-2xs tabular-nums text-text-muted">
                  {noData ? 'excluded' : `${Math.round(dim.weight * 100)}% weight`}
                </span>
              </div>
              <div className="mt-1 flex items-baseline gap-2">
                <span
                  className={`font-mono text-2xl font-semibold tabular-nums ${
                    noData ? 'text-text-muted line-through' : dimColor(dim.label)
                  }`}
                  title={noData ? 'No data — score excluded from composite' : ''}
                >
                  {dim.score}
                </span>
                <span className="font-mono text-xs tabular-nums text-text-muted">/100</span>
                <span
                  className={`ml-auto text-2xs font-semibold uppercase tracking-wide ${
                    noData ? 'text-text-muted' : dimColor(dim.label)
                  }`}
                >
                  {noData ? 'NO DATA' : dim.label}
                </span>
              </div>
              <p className="mt-1 text-xs text-text-secondary leading-snug">{dim.rationale}</p>
            </div>
          );
        })}
      </div>

      {/* Company Overview — what they do + current catalysts */}
      {report.company_overview && (
        <div className="mt-4 rounded-lg border border-accent-cyan/20 bg-accent-cyan/5 p-3">
          <h4 className="stat-label mb-1 text-accent-cyan">Company &amp; Current Catalysts</h4>
          <p className="text-sm text-text-primary leading-relaxed">{report.company_overview}</p>
        </div>
      )}

      {/* Investment Thesis */}
      {report.investment_thesis && (
        <div className="mt-4">
          <h4 className="stat-label mb-1">Investment Thesis</h4>
          <p className="text-sm text-text-primary leading-relaxed">{report.investment_thesis}</p>
        </div>
      )}

      {/* Key drivers */}
      {report.key_drivers && report.key_drivers.length > 0 && (
        <div className="mt-3">
          <h4 className="stat-label mb-1">Key Drivers</h4>
          <ol className="ml-4 list-decimal space-y-1 text-sm text-text-secondary">
            {report.key_drivers.map((d, i) => <li key={i}>{d}</li>)}
          </ol>
        </div>
      )}

      {/* Bull / Bear */}
      {(report.bull_case || report.bear_case) && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {report.bull_case && (
            <div className="rounded-lg border border-success-green/30 bg-success-green/5 p-3">
              <p className="stat-label text-success-green">BULL CASE</p>
              <p className="mt-1 text-sm text-text-secondary leading-relaxed">{report.bull_case}</p>
            </div>
          )}
          {report.bear_case && (
            <div className="rounded-lg border border-danger-red/30 bg-danger-red/5 p-3">
              <p className="stat-label text-danger-red">BEAR CASE</p>
              <p className="mt-1 text-sm text-text-secondary leading-relaxed">{report.bear_case}</p>
            </div>
          )}
        </div>
      )}

      {/* Action plan per investor type */}
      {report.action_plan && Object.keys(report.action_plan).length > 0 && (
        <div className="mt-3">
          <h4 className="stat-label mb-1">Action Plan</h4>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {Object.entries(report.action_plan).map(([who, action]) => (
              <div key={who} className="rounded-lg border border-border-subtle bg-bg-input/40 p-2 text-xs">
                <span className="font-semibold text-text-primary capitalize">
                  {who.replace(/_/g, ' ')}:
                </span>{' '}
                <span className="text-text-secondary">{action}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Catalysts strip */}
      {(report.next_earnings_date || report.analyst_target_median) && (
        <div className="mt-3 flex flex-wrap gap-3 rounded-lg border border-border-subtle bg-bg-input/40 p-3 text-xs">
          {report.next_earnings_date && (
            <div>
              <span className="text-text-muted">Next earnings:</span>{' '}
              <span className="font-mono tabular-nums text-text-primary">{report.next_earnings_date}</span>
            </div>
          )}
          {report.analyst_target_median && (
            <div>
              <span className="text-text-muted">Analyst median target:</span>{' '}
              <span className="font-mono tabular-nums text-text-primary">${report.analyst_target_median.toFixed(2)}</span>
              {report.analyst_count && (
                <span className="ml-1 font-mono tabular-nums text-text-muted">({report.analyst_count} analysts)</span>
              )}
            </div>
          )}
          {report.sector && (
            <div>
              <span className="text-text-muted">Sector:</span>{' '}
              <span className="text-text-primary">{report.sector}</span>
            </div>
          )}
        </div>
      )}

      {/* Bottom line */}
      {report.bottom_line && (
        <div className="mt-3 rounded-lg border-l-2 border-accent-cyan bg-accent-cyan/5 p-3">
          <p className="stat-label text-accent-cyan">Bottom Line</p>
          <p className="mt-1 text-sm font-medium text-text-primary leading-relaxed">{report.bottom_line}</p>
        </div>
      )}
    </motion.div>
  );
}

// ── LLM Commentary Card ──
function LLMCommentaryCard({ commentary, taConfidence }: { commentary: LLMCommentary; taConfidence: number }) {
  const agreementColor =
    commentary.agreement === 'agrees'
      ? 'text-success-green'
      : commentary.agreement === 'disagrees'
      ? 'text-danger-red'
      : 'text-warning-amber';
  const agreementBg =
    commentary.agreement === 'agrees'
      ? 'bg-success-green/10 border-success-green/30'
      : commentary.agreement === 'disagrees'
      ? 'bg-danger-red/10 border-danger-red/30'
      : 'bg-warning-amber/10 border-warning-amber/30';
  const impactPill =
    commentary.news_impact === 'high'
      ? 'pill-danger'
      : commentary.news_impact === 'medium'
      ? 'pill-warning'
      : commentary.news_impact === 'low'
      ? 'pill-info'
      : 'pill-neutral';
  const delta = commentary.adjusted_confidence - taConfidence;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.05 }}
      className={`mt-4 rounded-xl border p-4 ${agreementBg}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-accent-cyan" />
          <span className="text-sm font-semibold text-text-primary">LLM Second Opinion</span>
          <span className="font-mono text-2xs text-text-muted">{commentary.model}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={impactPill}>
            news: {commentary.news_impact}
          </span>
          <span className={`text-xs font-mono font-medium ${agreementColor}`}>
            {commentary.agreement}
          </span>
        </div>
      </div>

      {commentary.alternative_verdict && commentary.agreement === 'disagrees' && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-accent-cyan/40 bg-accent-cyan/5 px-3 py-2">
          <span className="text-xs text-text-muted">Recommends instead:</span>
          <span className={`text-base font-bold ${verdictColor(commentary.alternative_verdict)}`}>
            {commentary.alternative_verdict.replace('_', ' ')}
          </span>
        </div>
      )}

      <p className="text-sm leading-relaxed text-text-secondary mb-3">{commentary.rationale}</p>

      {commentary.key_factors.length > 0 && (
        <ul className="space-y-1 mb-3 text-xs text-text-secondary">
          {commentary.key_factors.map((f, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-accent-cyan">›</span>
              <span>{f}</span>
            </li>
          ))}
        </ul>
      )}

      {(commentary.risk_factors?.length || commentary.catalysts?.length) ? (
        <div className="mb-3 grid gap-3 sm:grid-cols-2 text-xs">
          {commentary.risk_factors && commentary.risk_factors.length > 0 && (
            <div className="rounded-lg border border-danger-red/30 bg-danger-red/5 p-2">
              <div className="stat-label mb-1 text-danger-red">Risks</div>
              <ul className="space-y-1 text-text-secondary">
                {commentary.risk_factors.map((r, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-danger-red">›</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {commentary.catalysts && commentary.catalysts.length > 0 && (
            <div className="rounded-lg border border-success-green/30 bg-success-green/5 p-2">
              <div className="stat-label mb-1 text-success-green">Catalysts</div>
              <ul className="space-y-1 text-text-secondary">
                {commentary.catalysts.map((c, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-success-green">›</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : null}

      <div className="flex items-center justify-between border-t border-border-subtle/50 pt-2 text-xs">
        <span className="text-text-muted">
          Adjusted confidence:{' '}
          <span className="font-mono font-medium tabular-nums text-text-primary">
            {commentary.adjusted_confidence.toFixed(1)}%
          </span>
          {Math.abs(delta) >= 0.5 && (
            <span className={`font-mono tabular-nums ml-1 ${delta > 0 ? 'text-success-green' : 'text-danger-red'}`}>
              ({delta > 0 ? '+' : ''}{delta.toFixed(1)} vs TA)
            </span>
          )}
        </span>
        <span className="text-text-muted font-mono tabular-nums">
          {commentary.article_count} article{commentary.article_count === 1 ? '' : 's'}
        </span>
      </div>
    </motion.div>
  );
}

// ── Main Advisor Page ──
export default function Advisor() {
  const location = useLocation();
  const navState = location.state as { symbol?: string; assetType?: 'crypto' | 'stock' } | null;

  const [symbol, setSymbol] = useState(navState?.symbol || '');
  const [assetType, setAssetType] = useState<'crypto' | 'stock'>(navState?.assetType || 'crypto');
  const [timeRange, setTimeRange] = useState<TimeRange>('90d');
  const [advanced, setAdvanced] = useState<boolean>(false);
  const [researchMode, setResearchMode] = useState<boolean>(false);
  const { result, research, loading, researchLoading, error, analyze, fetchResearch } = useAdvisor();
  const { items: watchItems } = useWatchlist();

  // Typeahead state — populated by /api/advisor/lookup as the user types
  const [lookupHits, setLookupHits] = useState<SymbolLookupHit[]>([]);
  const [lookupOpen, setLookupOpen] = useState(false);
  useEffect(() => {
    const q = symbol.trim();
    if (q.length < 1) {
      setLookupHits([]);
      return;
    }
    const handle = setTimeout(async () => {
      const hits = await lookupSymbol(q, 8);
      setLookupHits(hits);
    }, 200);
    return () => clearTimeout(handle);
  }, [symbol]);

  /**
   * Single fire path used by every analyze trigger (manual button, quick-select
   * chip, nav state from Watchlist, time-range click, typeahead pick). When
   * Research mode is on we ALWAYS kick off the deeper report in parallel —
   * earlier this was only wired in two of five paths, so picking a stock from
   * the Watchlist or clicking a quick-select chip silently skipped the
   * research call.
   */
  const runAnalyze = async (
    sym: string,
    type: 'crypto' | 'stock',
    days: number,
    adv: boolean,
  ) => {
    await analyze(sym, type, days, adv);
    if (researchMode) {
      fetchResearch(sym, type, days, adv).catch(() => {});
    }
  };

  useEffect(() => {
    if (navState?.symbol) {
      runAnalyze(
        navState.symbol,
        navState.assetType || 'crypto',
        rangeToDays(timeRange),
        advanced,
      ).catch(() => {});
      // Clear state so refresh doesn't re-trigger
      window.history.replaceState({}, document.title);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAnalyze = async () => {
    if (!symbol.trim()) {
      toast.error('Enter a symbol to analyze');
      return;
    }
    try {
      await runAnalyze(symbol.trim(), assetType, rangeToDays(timeRange), advanced);
    } catch {
      toast.error('Analysis failed. Check the symbol and try again.');
    }
  };

  const handleQuickSelect = (ticker: string) => {
    setSymbol(ticker);
    // Auto-detect asset type from ticker
    const isStock = quickSelectStocks.includes(ticker);
    const isCrypto = quickSelectCrypto.includes(ticker);
    if (isStock) setAssetType('stock');
    if (isCrypto) setAssetType('crypto');
    // Small delay so state updates before analyze
    setTimeout(() => {
      runAnalyze(
        ticker,
        isStock ? 'stock' : 'crypto',
        rangeToDays(timeRange),
        advanced,
      ).catch(() => {});
    }, 50);
  };

  const quickSelect = assetType === 'crypto' ? quickSelectCrypto : quickSelectStocks;

  return (
    <Layout>
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Hero Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center"
        >
          <h1 className="text-2xl font-bold tracking-tight text-text-primary">AI Trading Advisor</h1>
          <p className="stat-label mt-1.5 text-accent-cyan">AI-Powered Analysis</p>
          <p className="mt-2 text-sm text-text-secondary">
            Ask about any stock or crypto. Get professional-grade analysis.
          </p>
        </motion.div>

        {/* Search Card */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="panel p-5"
        >
          {/* Asset type toggle */}
          <div className="flex items-center justify-center">
            <div className="inline-flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
              <button
                onClick={() => setAssetType('crypto')}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${assetType === 'crypto' ? 'bg-bg-elevated text-text-primary shadow-card' : 'text-text-muted hover:text-text-secondary'}`}
              >
                Crypto
              </button>
              <button
                onClick={() => setAssetType('stock')}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${assetType === 'stock' ? 'bg-bg-elevated text-text-primary shadow-card' : 'text-text-muted hover:text-text-secondary'}`}
              >
                Stock
              </button>
            </div>
          </div>

          {/* Time ranges */}
          <div className="mt-3 flex items-center justify-center">
            <div className="inline-flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
              {timeRanges.map((r) => (
                <button
                  key={r.key}
                  onClick={() => {
                    const newRange = r.key;
                    setTimeRange(newRange);
                    if (symbol.trim() && !loading) {
                      runAnalyze(
                        symbol.trim(),
                        assetType,
                        rangeToDays(newRange),
                        advanced,
                      ).catch(() => {});
                    }
                  }}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    timeRange === r.key
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {/* Search input with typeahead by ticker OR company name */}
          <div className="mt-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                placeholder="Search by ticker or name: AAPL, Apple, NVDA, Bitcoin..."
                value={symbol}
                onChange={(e) => { setSymbol(e.target.value); setLookupOpen(true); }}
                onFocus={() => setLookupOpen(true)}
                onBlur={() => setTimeout(() => setLookupOpen(false), 150)}
                onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                className="w-full rounded-lg border border-border-subtle bg-bg-input py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              />
              {lookupOpen && lookupHits.length > 0 && (
                <ul className="panel absolute left-0 right-0 top-full z-20 mt-1 max-h-72 overflow-y-auto">
                  {lookupHits.map((hit) => (
                    <li
                      key={`${hit.asset_type}-${hit.symbol}`}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setSymbol(hit.symbol);
                        setAssetType(hit.asset_type);
                        setLookupOpen(false);
                        setLookupHits([]);
                        // Auto-run analysis when a typeahead hit is picked.
                        // Goes through runAnalyze so research-mode is honored
                        // consistently with all other entry points.
                        runAnalyze(
                          hit.symbol,
                          hit.asset_type,
                          rangeToDays(timeRange),
                          advanced,
                        ).catch(() => {});
                      }}
                      className="flex cursor-pointer items-center justify-between gap-3 border-b border-border-subtle/40 px-3 py-2 text-sm hover:bg-accent-cyan/10 last:border-b-0"
                    >
                      <div className="flex flex-1 items-center gap-2 min-w-0">
                        <span className="font-mono font-semibold text-accent-cyan shrink-0">{hit.symbol.toUpperCase()}</span>
                        <span className="truncate text-text-secondary">{hit.name}</span>
                      </div>
                      <span className="pill-neutral shrink-0">
                        {hit.asset_type}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <button
              onClick={handleAnalyze}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-accent-cyan px-3.5 py-2 text-xs font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              Analyze
            </button>
          </div>

          {/* Advanced + Research toggles */}
          <div className="mt-3 flex items-center justify-end gap-4">
            <label className="inline-flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={researchMode}
                onChange={(e) => {
                  const on = e.target.checked;
                  setResearchMode(on);
                  // If toggling ON and we already have an analyze result for
                  // this symbol, kick off research right away — saves the user
                  // a re-click of the analyze button.
                  if (on && result && symbol.trim() && !researchLoading) {
                    fetchResearch(
                      symbol.trim(),
                      assetType,
                      rangeToDays(timeRange),
                      advanced,
                    ).catch(() => {});
                  }
                }}
                className="h-3.5 w-3.5 rounded border-border-subtle bg-bg-input accent-accent-cyan"
              />
              <span className="text-xs text-text-muted">
                Research mode
                {researchMode && <span className="ml-1 text-accent-cyan">— multi-dimensional</span>}
              </span>
            </label>
            <label className="inline-flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={advanced}
                onChange={(e) => setAdvanced(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border-subtle bg-bg-input accent-accent-cyan"
              />
              <span className="text-xs text-text-muted">
                Advanced (cloud LLM)
                {advanced && <span className="ml-1 text-accent-cyan">— OpenRouter</span>}
              </span>
            </label>
          </div>

          {/* Quick select */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="stat-label">Quick select:</span>
            {quickSelect.map((ticker) => (
              <button
                key={ticker}
                onClick={() => handleQuickSelect(ticker)}
                className="rounded-full border border-border-subtle bg-bg-input px-2.5 py-0.5 font-mono text-xs font-medium text-text-secondary transition-colors hover:border-accent-cyan/30 hover:text-text-primary"
              >
                {ticker}
              </button>
            ))}
          </div>
        </motion.div>

        {/* Empty state — fill the space below the search card with a real
            launchpad (watchlist quick-analyze) + what the analysis covers,
            instead of a blank void. Only when there's nothing to show yet. */}
        {!result && !loading && !error && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="space-y-5"
          >
            {watchItems.length > 0 && (
              <div className="panel p-5">
                <div className="mb-3 flex items-center gap-2">
                  <Target className="h-4 w-4 text-accent-cyan" />
                  <h3 className="text-sm font-semibold text-text-primary">Your Watchlist</h3>
                  <span className="ml-auto text-2xs text-text-muted">tap to analyze</span>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                  {watchItems.slice(0, 12).map((it) => (
                    <button
                      key={`${it.asset_type}-${it.symbol}`}
                      onClick={() => {
                        setSymbol(it.symbol);
                        setAssetType(it.asset_type);
                        runAnalyze(
                          it.symbol,
                          it.asset_type,
                          rangeToDays(timeRange),
                          advanced,
                        ).catch(() => {});
                      }}
                      className="group flex items-center justify-between gap-2 rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-left transition-colors hover:border-accent-cyan/30"
                    >
                      <div className="min-w-0">
                        <p className="font-mono text-sm font-semibold text-text-primary group-hover:text-accent-cyan">
                          {it.symbol.toUpperCase()}
                        </p>
                        <p className="stat-label truncate">
                          {it.source}
                        </p>
                      </div>
                      <span className="pill-neutral shrink-0">
                        {it.asset_type}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* What the analysis covers */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                { icon: <Activity className="h-4 w-4 text-accent-cyan" />, title: 'Technical', desc: 'RSI, MACD, moving averages & Bollinger bands, with concrete price targets and stops.' },
                { icon: <Target className="h-4 w-4 text-accent-cyan" />, title: 'Fundamental', desc: 'Valuation, earnings, analyst targets and sector context — flagged when data is missing.' },
                { icon: <Brain className="h-4 w-4 text-accent-cyan" />, title: 'Sentiment + AI', desc: 'News-driven sentiment with an LLM second opinion that can agree, disagree, or flag risk.' },
              ].map((c) => (
                <div key={c.title} className="panel p-4">
                  <div className="mb-1.5 flex items-center gap-2">
                    {c.icon}
                    <span className="text-sm font-semibold text-text-primary">{c.title}</span>
                  </div>
                  <p className="text-xs leading-relaxed text-text-secondary">{c.desc}</p>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* Error */}
        {error && (
          <div className="panel border-danger-red/30 bg-danger-red/5 p-4 text-sm text-danger-red">
            {error}
          </div>
        )}

        {/* Results */}
        <AnimatePresence>
          {result && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              className="space-y-4"
            >
              {/* Verdict Card */}
              <div className="panel p-5">
                {/* Symbol header — company/coin name and big price up top */}
                <div className="mb-4 flex items-end justify-between border-b border-border-subtle pb-3">
                  <div>
                    <p className="stat-label">
                      {result.symbol.toUpperCase()}
                      {result.exchange && (
                        <span className="ml-2 text-text-muted/70">· {result.exchange}</span>
                      )}
                      {result.sector && (
                        <span className="ml-2 text-text-muted/70">· {result.sector}</span>
                      )}
                    </p>
                    <h3 className="mt-0.5 text-xl font-semibold text-text-primary">
                      {result.display_name || result.symbol.toUpperCase()}
                    </h3>
                  </div>
                  <div className="text-right">
                    <p className="stat-label">Last price</p>
                    <p className="font-mono text-[26px] font-semibold leading-8 tabular-nums tracking-tight text-text-primary">
                      {formatCurrency(result.current_price)}
                    </p>
                  </div>
                </div>

                <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`flex h-14 w-14 items-center justify-center rounded-full ${verdictBg(result.verdict)} bg-opacity-20 text-text-inverse`}>
                      {verdictIcon(result.verdict)}
                    </div>
                    <div>
                      <h2 className={`text-2xl font-bold tracking-tight ${verdictColor(result.verdict)}`}>
                        {result.verdict.replace('_', ' ')}
                      </h2>
                      <p className="text-xs text-text-muted">
                        Verdict for {result.symbol.toUpperCase()}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-center">
                      <p className="stat-label">Confidence</p>
                      <p className="font-mono text-lg font-semibold tabular-nums text-text-primary">{result.confidence.toFixed(0)}%</p>
                    </div>
                    <div className="text-center">
                      <p className="stat-label">Risk</p>
                      <span className={result.risk_level === 'low' ? 'pill-success' : result.risk_level === 'moderate' ? 'pill-warning' : 'pill-danger'}>
                        {result.risk_level}
                      </span>
                    </div>
                    <div className="text-center">
                      <p className="stat-label">Horizon</p>
                      <p className="text-sm font-medium text-text-primary">{timeHorizonLabel(result.time_horizon)}</p>
                    </div>
                  </div>
                </div>

                {/* Summary */}
                <div className="mt-4 rounded-lg bg-bg-input p-3">
                  <p className="text-sm leading-relaxed text-text-secondary">{result.summary}</p>
                </div>

                {/* LLM Commentary — hidden when Research Mode supersedes it */}
                {result.llm_commentary && !research && !researchLoading && (
                  <LLMCommentaryCard commentary={result.llm_commentary} taConfidence={result.confidence} />
                )}
              </div>

              {/* Multi-Dimensional Research Report */}
              {researchLoading && !research && (
                <div className="panel border-accent-cyan/30 p-5">
                  <div className="flex items-center gap-3 text-sm text-text-muted">
                    <Loader2 className="h-4 w-4 animate-spin text-accent-cyan" />
                    Generating multi-dimensional research report…
                  </div>
                </div>
              )}
              {research && <ResearchReportCard report={research} />}

              {/* Chart */}
              {result.chart_data && result.chart_data.ohlcv && result.chart_data.ohlcv.close && result.chart_data.ohlcv.close.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.1 }}
                  className="panel p-5"
                >
                  <h3 className="text-sm font-semibold text-text-primary mb-3">Price Chart</h3>
                  <PriceChart
                    chartData={{
                      timestamps: result.chart_data.timestamps,
                      close: result.chart_data.ohlcv.close,
                      sma_20: result.chart_data.sma_20,
                      sma_50: result.chart_data.sma_50,
                      ema_20: result.chart_data.ema_20,
                      ema_50: result.chart_data.ema_50,
                      bb_upper: result.chart_data.bb_upper,
                      bb_lower: result.chart_data.bb_lower,
                    }}
                  />
                </motion.div>
              )}

              {/* Two-column layout: Indicators + Targets/Risk */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {/* Indicators */}
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                  className="panel p-5"
                >
                  <div className="mb-3 flex items-center gap-2">
                    <Activity className="h-4 w-4 text-accent-cyan" />
                    <h3 className="text-sm font-semibold text-text-primary">Technical Indicators</h3>
                    <span className="ml-auto font-mono text-2xs tabular-nums text-text-muted">{result.indicators.length} signals</span>
                  </div>
                  {/* Grow naturally so the indicator card matches the height
                      of the Price-Targets + Risk-Sizing column on the right
                      instead of cropping at a fixed 400px. */}
                  <div className="space-y-2">
                    {result.indicators.map((ind, i) => (
                      <IndicatorCard key={`${ind.name}-${i}`} reading={ind} />
                    ))}
                  </div>
                </motion.div>

                {/* Price Targets & Risk */}
                <div className="space-y-4">
                  {/* Price Targets */}
                  <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.25 }}
                    className="panel p-5"
                  >
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Target className="h-4 w-4 text-accent-cyan" />
                        <h3 className="text-sm font-semibold text-text-primary">Price Targets</h3>
                      </div>
                      <span className="stat-label">
                        {result.price_targets.length} levels
                      </span>
                    </div>
                    <div className="space-y-2">
                      {result.price_targets.map((t, i) => (
                        <PriceTargetCard key={`${t.label}-${i}`} target={t} currentPrice={result.current_price} />
                      ))}
                    </div>
                  </motion.div>

                  {/* Risk & Sizing */}
                  <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                    className="panel p-5"
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <Shield className="h-4 w-4 text-accent-cyan" />
                      <h3 className="text-sm font-semibold text-text-primary">Risk & Position Sizing</h3>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-lg bg-bg-input p-3">
                        <p className="stat-label">Position Size</p>
                        <p className="mt-1 font-mono text-sm tabular-nums text-text-primary">{(result.suggested_position_size * 100).toFixed(1)}%</p>
                      </div>
                      <div className="rounded-lg bg-bg-input p-3">
                        <p className="stat-label">Entry Zone</p>
                        <p className="mt-1 font-mono text-sm tabular-nums text-text-primary">
                          {formatCurrency(result.entry_zone_low)} – {formatCurrency(result.entry_zone_high)}
                        </p>
                      </div>
                      <div className="rounded-lg bg-bg-input p-3">
                        <p className="stat-label">Stop Loss</p>
                        <p className="mt-1 font-mono text-sm tabular-nums text-danger-red">{formatCurrency(result.stop_loss)}</p>
                      </div>
                      <div className="rounded-lg bg-bg-input p-3">
                        <p className="stat-label">Take Profit</p>
                        <p className="mt-1 font-mono text-sm tabular-nums text-success-green">{formatCurrency(result.take_profit)}</p>
                      </div>
                    </div>
                  </motion.div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Layout>
  );
}
