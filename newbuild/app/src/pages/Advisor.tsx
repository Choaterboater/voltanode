import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
import Badge from '@/components/Badge';
import { useAdvisor, type IndicatorReading, type PriceTarget } from '@/hooks/useAdvisor';
import { toast } from 'sonner';

type TimeRange = '7d' | '28d' | '180d';

const timeRanges: { key: TimeRange; label: string }[] = [
  { key: '7d', label: '1–7d' },
  { key: '28d', label: '1–4w' },
  { key: '180d', label: '1–6m' },
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

function signalBadgeVariant(signal: string): 'success' | 'danger' | 'warning' | 'info' | 'cyan' {
  if (signal === 'bullish') return 'success';
  if (signal === 'bearish') return 'danger';
  return 'warning';
}

function formatCurrency(v: number) {
  if (v >= 1000) return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `$${v.toFixed(4)}`;
}

function timeHorizonLabel(h: string) {
  if (h === 'short_term') return 'Short Term (1–4 weeks)';
  if (h === 'medium_term') return 'Medium Term (1–3 months)';
  return 'Long Term (3–12 months)';
}

function rangeToDays(range: TimeRange): number {
  if (range === '7d') return 7;
  if (range === '28d') return 28;
  return 180;
}

// ── Indicator Card ──
function IndicatorCard({ reading }: { reading: IndicatorReading }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <motion.div
      layout
      className="rounded-lg border border-border-subtle bg-bg-surface p-3 cursor-pointer hover:border-border-active transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant={signalBadgeVariant(reading.signal)}>
            {reading.signal.charAt(0).toUpperCase() + reading.signal.slice(1)}
          </Badge>
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
            <p className="mt-1 font-mono text-xs text-text-muted">Value: {reading.value}</p>
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
    <div className="flex items-center justify-between rounded-lg border border-border-subtle bg-bg-surface p-3">
      <div>
        <p className="text-xs font-medium text-text-primary">{target.label}</p>
        <p className="text-xs text-text-muted mt-0.5">{target.rationale}</p>
      </div>
      <div className="text-right">
        <p className={`font-mono text-sm font-medium ${isAbove ? 'text-success-green' : 'text-danger-red'}`}>
          {formatCurrency(target.price)}
        </p>
        <p className="text-xs text-text-muted">{isAbove ? '+' : '-'}{pct.toFixed(1)}%</p>
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
        <ComposedChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00D4FF" stopOpacity={0.15} />
              <stop offset="100%" stopColor="#00D4FF" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#152033" strokeOpacity={0.3} vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: '#5A6A7D', fontSize: 11, fontFamily: 'JetBrains Mono, ui-monospace, monospace' }}
            axisLine={{ stroke: '#152033' }}
            tickLine={false}
            minTickGap={30}
          />
          <YAxis
            tick={{ fill: '#5A6A7D', fontSize: 11, fontFamily: 'JetBrains Mono, ui-monospace, monospace' }}
            axisLine={false}
            tickLine={false}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => `$${v < 1 ? v.toFixed(4) : v.toFixed(0)}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0D1320',
              border: '1px solid #152033',
              borderRadius: '8px',
              fontFamily: 'JetBrains Mono, ui-monospace, monospace',
              fontSize: '12px',
              color: '#F0F4F8',
            }}
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
          <Area type="monotone" dataKey="close" stroke="#00D4FF" strokeWidth={2} fill="url(#priceGradient)" dot={false} />
          <Line type="monotone" dataKey="sma20" stroke="#10B981" strokeWidth={1} dot={false} strokeDasharray="4 4" />
          <Line type="monotone" dataKey="sma50" stroke="#A855F7" strokeWidth={1} dot={false} strokeDasharray="4 4" />
          {chartData.bb_upper && <Line type="monotone" dataKey="bbUpper" stroke="#FF5252" strokeWidth={1} dot={false} strokeOpacity={0.5} />}
          {chartData.bb_lower && <Line type="monotone" dataKey="bbLower" stroke="#FF5252" strokeWidth={1} dot={false} strokeOpacity={0.5} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main Advisor Page ──
export default function Advisor() {
  const [symbol, setSymbol] = useState('');
  const [assetType, setAssetType] = useState<'crypto' | 'stock'>('crypto');
  const [timeRange, setTimeRange] = useState<TimeRange>('28d');
  const { result, loading, error, analyze } = useAdvisor();

  const handleAnalyze = async () => {
    if (!symbol.trim()) {
      toast.error('Enter a symbol to analyze');
      return;
    }
    try {
      await analyze(symbol.trim(), assetType, rangeToDays(timeRange));
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
      analyze(ticker, isStock ? 'stock' : 'crypto', rangeToDays(timeRange));
    }, 50);
  };

  const quickSelect = assetType === 'crypto' ? quickSelectCrypto : quickSelectStocks;

  return (
    <Layout title="Advisor">
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Hero Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center"
        >
          <h1 className="text-2xl font-bold text-text-primary">AI Trading Advisor</h1>
          <p className="mt-1 text-sm font-medium text-accent-cyan">AI-Powered Analysis</p>
          <p className="mt-2 text-xs text-text-muted">
            Ask about any stock or crypto. Get professional-grade analysis.
          </p>
        </motion.div>

        {/* Search Card */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          {/* Asset type toggle */}
          <div className="flex items-center justify-center">
            <div className="flex items-center rounded-md bg-bg-input border border-border-subtle p-0.5">
              <button
                onClick={() => setAssetType('crypto')}
                className={`rounded px-4 py-1.5 text-xs font-medium transition-colors ${assetType === 'crypto' ? 'bg-bg-elevated text-accent-cyan' : 'text-text-secondary hover:text-text-primary'}`}
              >
                Crypto
              </button>
              <button
                onClick={() => setAssetType('stock')}
                className={`rounded px-4 py-1.5 text-xs font-medium transition-colors ${assetType === 'stock' ? 'bg-bg-elevated text-accent-cyan' : 'text-text-secondary hover:text-text-primary'}`}
              >
                Stock
              </button>
            </div>
          </div>

          {/* Time ranges */}
          <div className="mt-3 flex items-center justify-center gap-1">
            {timeRanges.map((r) => (
              <button
                key={r.key}
                onClick={() => {
                  const newRange = r.key;
                  setTimeRange(newRange);
                  if (symbol.trim() && !loading) {
                    analyze(symbol.trim(), assetType, rangeToDays(newRange));
                  }
                }}
                className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                  timeRange === r.key
                    ? 'bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/20'
                    : 'text-text-muted hover:text-text-secondary border border-transparent'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>

          {/* Search input */}
          <div className="mt-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-text-muted" />
              <input
                type="text"
                placeholder={assetType === 'crypto' ? 'Enter ticker: BTC, ETH, AAPL, TSLA, NVDA...' : 'Enter ticker: AAPL, TSLA, NVDA...'}
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                className="w-full rounded-md border border-border-subtle bg-bg-input py-2.5 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <button
              onClick={handleAnalyze}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-accent-cyan px-5 py-2.5 text-sm font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              Analyze
            </button>
          </div>

          {/* Quick select */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-text-muted">Quick select:</span>
            {quickSelect.map((ticker) => (
              <button
                key={ticker}
                onClick={() => handleQuickSelect(ticker)}
                className="rounded-full border border-border-subtle bg-bg-input px-2.5 py-0.5 text-xs font-medium text-text-secondary hover:border-accent-cyan hover:text-accent-cyan transition-colors"
              >
                {ticker}
              </button>
            ))}
          </div>
        </motion.div>

        {/* Error */}
        {error && (
          <div className="rounded-[10px] border border-danger-red/30 bg-danger-red/5 p-4 text-sm text-danger-red">
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
              <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
                <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`flex h-14 w-14 items-center justify-center rounded-full ${verdictBg(result.verdict)} bg-opacity-20 text-text-inverse`}>
                      {verdictIcon(result.verdict)}
                    </div>
                    <div>
                      <h2 className={`text-2xl font-bold ${verdictColor(result.verdict)}`}>
                        {result.verdict.replace('_', ' ')}
                      </h2>
                      <p className="text-xs text-text-muted">
                        {result.symbol.toUpperCase()} · {formatCurrency(result.current_price)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Confidence</p>
                      <p className="font-mono text-lg font-semibold text-text-primary">{result.confidence.toFixed(0)}%</p>
                    </div>
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Risk</p>
                      <Badge variant={result.risk_level === 'low' ? 'success' : result.risk_level === 'moderate' ? 'warning' : 'danger'}>
                        {result.risk_level}
                      </Badge>
                    </div>
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Horizon</p>
                      <p className="text-sm font-medium text-text-primary">{timeHorizonLabel(result.time_horizon)}</p>
                    </div>
                  </div>
                </div>

                {/* Summary */}
                <div className="mt-4 rounded-md bg-bg-input p-3">
                  <p className="text-sm leading-relaxed text-text-secondary">{result.summary}</p>
                </div>
              </div>

              {/* Chart */}
              {result.chart_data && result.chart_data.ohlcv && result.chart_data.ohlcv.close && result.chart_data.ohlcv.close.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.1 }}
                  className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
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
                  className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
                >
                  <div className="mb-3 flex items-center gap-2">
                    <Activity className="h-4 w-4 text-accent-cyan" />
                    <h3 className="text-sm font-semibold text-text-primary">Technical Indicators</h3>
                    <span className="ml-auto text-xs text-text-muted">{result.indicators.length} signals</span>
                  </div>
                  <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
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
                    className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <Target className="h-4 w-4 text-accent-cyan" />
                      <h3 className="text-sm font-semibold text-text-primary">Price Targets</h3>
                    </div>
                    <div className="space-y-2">
                      {result.price_targets.slice(0, 6).map((t, i) => (
                        <PriceTargetCard key={`${t.label}-${i}`} target={t} currentPrice={result.current_price} />
                      ))}
                    </div>
                  </motion.div>

                  {/* Risk & Sizing */}
                  <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                    className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <Shield className="h-4 w-4 text-accent-cyan" />
                      <h3 className="text-sm font-semibold text-text-primary">Risk & Position Sizing</h3>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-md bg-bg-input p-3">
                        <p className="text-xs text-text-muted">Position Size</p>
                        <p className="mt-1 font-mono text-sm text-text-primary">{(result.suggested_position_size * 100).toFixed(1)}%</p>
                      </div>
                      <div className="rounded-md bg-bg-input p-3">
                        <p className="text-xs text-text-muted">Entry Zone</p>
                        <p className="mt-1 font-mono text-sm text-text-primary">
                          {formatCurrency(result.entry_zone_low)} – {formatCurrency(result.entry_zone_high)}
                        </p>
                      </div>
                      <div className="rounded-md bg-bg-input p-3">
                        <p className="text-xs text-text-muted">Stop Loss</p>
                        <p className="mt-1 font-mono text-sm text-danger-red">{formatCurrency(result.stop_loss)}</p>
                      </div>
                      <div className="rounded-md bg-bg-input p-3">
                        <p className="text-xs text-text-muted">Take Profit</p>
                        <p className="mt-1 font-mono text-sm text-success-green">{formatCurrency(result.take_profit)}</p>
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
