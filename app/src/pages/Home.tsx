import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import { useDashboardData } from '@/hooks/useDashboard';
import {
  toggleStrategy,
  getSignals,
  type ApiStrategy,
  type SignalsSnapshot,
} from '@/lib/api';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from 'recharts';
import {
  Wallet,
  TrendingUp,
  BarChart3,
  Target,
  Bell,
  ChevronDown,
  Pause,
  Play,
  Settings,
  Plus,
  PlayCircle,
  AlertTriangle,
  CheckCircle,
} from 'lucide-react';
import Layout from '@/components/Layout';
import MetricCard from '@/components/MetricCard';
import Badge from '@/components/Badge';
import StatusDot from '@/components/StatusDot';
import DataTable from '@/components/DataTable';
import type { Trade } from '@/types';

const timeRanges = ['1H', '24H', '7D', '30D', 'ALL'];

function MiniSparkline({ data, color }: { data: number[]; color: string }) {
  const chartData = data.map((v, i) => ({ v, i }));
  return (
    <div className="h-10 w-24">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function DonutChart({ percentage }: { percentage: number }) {
  const data = [
    { name: 'filled', value: percentage },
    { name: 'empty', value: 100 - percentage },
  ];
  return (
    <div className="h-14 w-14">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={16}
            outerRadius={24}
            startAngle={90}
            endAngle={-270}
            dataKey="value"
            stroke="none"
          >
            <Cell fill="#06B6D4" />
            <Cell fill="#1E293B" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Signals Strip — macro / sentiment / catalysts at a glance ──
function SignalTile({
  label, value, sub, tone, onClick,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'positive' | 'negative' | 'neutral' | 'warning';
  onClick?: () => void;
}) {
  const toneClass =
    tone === 'positive' ? 'text-success-green'
    : tone === 'negative' ? 'text-danger-red'
    : tone === 'warning' ? 'text-warning-amber'
    : 'text-text-primary';
  return (
    <button
      onClick={onClick}
      type="button"
      className="flex flex-col rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-left transition-colors hover:border-accent-cyan/40"
    >
      <span className="text-[10px] uppercase tracking-wider text-text-muted">{label}</span>
      <span className={`mt-0.5 font-mono text-base font-semibold tabular-nums ${toneClass}`}>{value}</span>
      {sub && <span className="text-[10px] text-text-muted">{sub}</span>}
    </button>
  );
}

function SignalsStrip({ signals }: { signals: SignalsSnapshot | null }) {
  if (!signals) {
    return (
      <div className="rounded-[10px] border border-border-subtle bg-bg-surface px-4 py-2 text-xs text-text-muted">
        Loading market signals…
      </div>
    );
  }

  const fg = signals.fear_greed;
  const macro = signals.macro?.series ?? {};
  const vix = macro['VIXCLS'];
  const fed = macro['DFF'];
  const ten = macro['DGS10'];
  const spread = macro['T10Y2Y'];

  const fgTone =
    !fg ? 'neutral'
    : fg.is_extreme_fear ? 'positive'  // contrarian buy zone
    : fg.is_extreme_greed ? 'warning'  // caution
    : fg.value < 45 ? 'negative'
    : fg.value > 55 ? 'positive'
    : 'neutral';

  const vixTone =
    !vix?.value ? 'neutral'
    : vix.value > 30 ? 'negative'
    : vix.value > 20 ? 'warning'
    : 'positive';

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
      {fg && (
        <SignalTile
          label="Fear & Greed"
          value={`${fg.value}`}
          sub={fg.label}
          tone={fgTone}
        />
      )}
      {vix && (
        <SignalTile
          label="VIX"
          value={vix.value !== null ? vix.value.toFixed(2) : '—'}
          sub={vix.value && vix.value > 30 ? 'panic zone' : vix.value && vix.value > 20 ? 'elevated' : 'calm'}
          tone={vixTone}
        />
      )}
      {fed && (
        <SignalTile
          label="Fed Funds"
          value={fed.value !== null ? `${fed.value.toFixed(2)}%` : '—'}
          sub={fed.change != null ? `Δ ${fed.change >= 0 ? '+' : ''}${fed.change.toFixed(2)}` : ''}
        />
      )}
      {ten && (
        <SignalTile
          label="10Y Treasury"
          value={ten.value !== null ? `${ten.value.toFixed(2)}%` : '—'}
          sub={ten.change != null ? `Δ ${ten.change >= 0 ? '+' : ''}${ten.change.toFixed(2)}` : ''}
        />
      )}
      {spread && (
        <SignalTile
          label="10Y-2Y"
          value={spread.value !== null ? `${spread.value >= 0 ? '+' : ''}${spread.value.toFixed(2)}` : '—'}
          sub={spread.value !== null && spread.value < 0 ? 'inverted' : 'normal'}
          tone={spread.value !== null && spread.value < 0 ? 'negative' : 'positive'}
        />
      )}
      {signals.providers && !signals.providers.fred && (
        <SignalTile
          label="Macro feed"
          value="off"
          sub="set FRED_API_KEY"
          tone="neutral"
        />
      )}
    </div>
  );
}

export default function Home() {
  const [selectedRange, setSelectedRange] = useState('30D');
  const [notificationCount] = useState(3);
  const [signals, setSignals] = useState<SignalsSnapshot | null>(null);
  const navigate = useNavigate();
  const {
    portfolio,
    positions,
    tickers,
    trades,
    strategies,
    loading,
    error,
    refetch,
    equityHistory,
    allocation,
    performance: perfMetricsRaw,
    alerts,
  } = useDashboardData();
  const perfMetrics = perfMetricsRaw ?? {
    winRate: null, sharpeRatio: null, maxDrawdownPercent: null,
    profitFactor: null, tradesPerDay: null, totalTrades: 0,
  };

  // Pull macro / sentiment signals once per dashboard load + every 5 min after.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      getSignals().then((s) => { if (!cancelled) setSignals(s); }).catch(() => {});
    };
    load();
    const interval = setInterval(load, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  async function handleToggleBot(id: string, current: boolean) {
    try {
      await toggleStrategy(id, !current);
      await refetch?.();
    } catch {
      // Silently ignore — error surfaces via dashboard error state on next poll.
    }
  }

  const runningCount = strategies.filter((s: ApiStrategy) => s.is_active).length;

  // Real equity-curve data derived from broker snapshots stored backend-side.
  const equityCurve = (equityHistory ?? []).map((p) => ({
    date: new Date(p.ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    equity: p.equity,
  }));
  const allocList = allocation ?? [];
  // Trailing equity points double as a balance sparkline; if we have nothing
  // yet (fresh account, no snapshots written) we pass an empty array and the
  // sparkline component renders nothing.
  const balanceSpark = equityCurve.slice(-24).map((p) => p.equity);
  // Approx PnL spark: equity delta vs first observation in the window.
  const pnlSpark = balanceSpark.length > 0
    ? balanceSpark.map((v) => v - balanceSpark[0])
    : [];
  const fmtMetric = (v: number | null, digits = 2, suffix = '') =>
    v === null || !isFinite(v) ? '—' : `${v.toFixed(digits)}${suffix}`;

  const formatCurrency = (v: number) =>
    `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const formatPercent = (v: number) => `${v.toFixed(2)}%`;

  const topBarRight = (
    <>
      {/* Time range selector */}
      <div className="hidden items-center rounded-md bg-bg-surface border border-border-subtle p-0.5 md:flex">
        {timeRanges.map((range) => (
          <button
            key={range}
            onClick={() => setSelectedRange(range)}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              selectedRange === range
                ? 'bg-bg-elevated text-accent-cyan'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {range}
          </button>
        ))}
      </div>
      {/* Notification bell */}
      <button className="relative rounded-full p-2 text-text-secondary hover:bg-bg-surface hover:text-text-primary transition-colors">
        <Bell className="h-5 w-5" />
        {notificationCount > 0 && (
          <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-accent-cyan" />
        )}
      </button>
      {/* Account switcher */}
      <button className="flex items-center gap-2 rounded-md border border-border-subtle bg-bg-surface px-3 py-1.5 text-xs text-text-primary hover:bg-bg-elevated transition-colors">
        <span>Paper Account</span>
        <ChevronDown className="h-3.5 w-3.5 text-text-muted" />
      </button>
    </>
  );

  const longCount = positions.filter((p) => p.side === 'long').length;
  const shortCount = positions.filter((p) => p.side === 'short').length;
  const totalPos = longCount + shortCount;

  const tradeColumns = [
    {
      key: 'time',
      header: 'Time',
      render: (row: Trade) => (
        <span className="font-mono text-xs text-text-muted">{row.time}</span>
      ),
    },
    {
      key: 'symbol',
      header: 'Pair',
      render: (row: Trade) => (
        <span className="font-mono text-sm text-text-primary">{row.symbol}</span>
      ),
    },
    {
      key: 'side',
      header: 'Side',
      render: (row: Trade) => (
        <Badge variant={row.side === 'long' ? 'success' : 'danger'}>
          {row.side === 'long' ? 'Long' : 'Short'}
        </Badge>
      ),
    },
    {
      key: 'price',
      header: 'Price',
      render: (row: Trade) => (
        <span className="font-mono text-sm text-text-primary">
          {formatCurrency(row.price)}
        </span>
      ),
    },
    {
      key: 'size',
      header: 'Size',
      render: (row: Trade) => (
        <span className="font-mono text-sm text-text-primary">{row.size}</span>
      ),
    },
    {
      key: 'pnl',
      header: 'P&L',
      render: (row: Trade) => (
        row.pnl === 0 ? (
          <span className="font-mono text-xs text-text-muted">open</span>
        ) : (
          <span
            className={`font-mono text-sm tabular-nums ${
              row.pnl >= 0 ? 'text-success-green' : 'text-danger-red'
            }`}
          >
            {row.pnl >= 0 ? '+' : ''}
            {formatCurrency(row.pnl)}
          </span>
        )
      ),
    },
    {
      key: 'strategy',
      header: 'Bot',
      render: (row: Trade) => {
        // Show the strategy_type prefix (e.g. "simple_trend") for readability
        // — full id with timestamp is long. Falls back to "Manual" for
        // operator-initiated orders (flatten, etc.).
        const sid = String(row.strategy ?? '');
        const short = sid.split('_').slice(0, -1).join('_') || sid || 'Manual';
        return (
          <span className="font-mono text-[11px] text-text-secondary truncate max-w-[140px] inline-block" title={sid}>
            {short}
          </span>
        );
      },
    },
  ];

  const alertIconMap: Record<string, React.ReactNode> = {
    Play: <PlayCircle className="h-4 w-4 text-success-green" />,
    Target: <Target className="h-4 w-4 text-accent-cyan" />,
    AlertTriangle: <AlertTriangle className="h-4 w-4 text-warning-amber" />,
    CheckCircle: <CheckCircle className="h-4 w-4 text-success-green" />,
  };

  const alertBorderMap: Record<string, string> = {
    success: 'border-l-success-green',
    info: 'border-l-accent-cyan',
    warning: 'border-l-warning-amber',
    error: 'border-l-danger-red',
  };

  if (loading) {
    return (
      <Layout title="Dashboard" rightContent={topBarRight}>
        <div className="flex h-64 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-cyan border-t-transparent" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Dashboard" rightContent={topBarRight}>
      {error && (
        <div className="rounded-lg border border-danger-red/30 bg-danger-red/10 px-4 py-2 text-sm text-danger-red">
          {error}
        </div>
      )}
      <div className="space-y-5">
        {/* Signals Strip — macro / sentiment / catalysts at a glance */}
        <SignalsStrip signals={signals} />

        {/* Section 1: Hero Metrics Row */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:gap-5">
          <MetricCard
            label="Total Virtual Balance"
            value={formatCurrency(portfolio.totalEquity)}
            delta={`${portfolio.totalPnlPercent >= 0 ? '+' : ''}${portfolio.totalPnlPercent.toFixed(2)}%`}
            deltaPositive={portfolio.totalPnlPercent >= 0}
            icon={<Wallet className="h-5 w-5" />}
            delay={0}
          >
            {balanceSpark.length > 0 && <MiniSparkline data={balanceSpark} color="#10B981" />}
          </MetricCard>

          <MetricCard
            label="Unrealized P&L"
            value={`${portfolio.dailyPnl >= 0 ? '+' : ''}${formatCurrency(portfolio.dailyPnl)}`}
            delta={`${portfolio.dailyPnlPercent.toFixed(2)}%`}
            deltaPositive={portfolio.dailyPnl >= 0}
            icon={<TrendingUp className="h-5 w-5 text-success-green" />}
            delay={0.08}
          >
            {pnlSpark.length > 0 && <MiniSparkline data={pnlSpark} color="#10B981" />}
          </MetricCard>

          <MetricCard
            label="Active Positions"
            value={`${totalPos}`}
            delta={`${longCount} long / ${shortCount} short`}
            deltaTone="neutral"
            icon={<BarChart3 className="h-5 w-5" />}
            delay={0.16}
          >
            <div className="mt-1 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted w-12">Longs</span>
                <div className="flex-1 h-1.5 rounded-full bg-bg-input overflow-hidden">
                  <div
                    className="h-full rounded-full bg-success-green"
                    style={{ width: totalPos > 0 ? `${(longCount / totalPos) * 100}%` : '0%' }}
                  />
                </div>
                <span className="text-xs font-mono text-text-secondary w-8">{totalPos > 0 ? Math.round((longCount / totalPos) * 100) : 0}%</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted w-12">Shorts</span>
                <div className="flex-1 h-1.5 rounded-full bg-bg-input overflow-hidden">
                  <div
                    className="h-full rounded-full bg-danger-red"
                    style={{ width: totalPos > 0 ? `${(shortCount / totalPos) * 100}%` : '0%' }}
                  />
                </div>
                <span className="text-xs font-mono text-text-secondary w-8">{totalPos > 0 ? Math.round((shortCount / totalPos) * 100) : 0}%</span>
              </div>
            </div>
          </MetricCard>

          <MetricCard
            label="Win Rate (30D)"
            value={perfMetrics.winRate === null ? '—' : formatPercent(perfMetrics.winRate)}
            delta={perfMetrics.totalTrades === 0 ? 'awaiting closes' : `${perfMetrics.totalTrades} closed`}
            deltaTone="neutral"
            icon={<Target className="h-5 w-5" />}
            delay={0.24}
          >
            {perfMetrics.winRate === null || perfMetrics.totalTrades === 0 ? (
              <div className="flex items-center gap-3 text-xs text-text-muted">
                <div className="h-12 w-12 rounded-full border-2 border-dashed border-border-subtle" />
                <span>No closed trades<br/>yet — donut fills in once<br/>SELL fills land.</span>
              </div>
            ) : perfMetrics.winRate === 0 ? (
              <div className="flex items-center gap-3 text-xs text-text-muted">
                <div className="flex h-12 w-12 items-center justify-center rounded-full border-2 border-danger-red/40">
                  <span className="font-mono text-xs text-danger-red">0/{perfMetrics.totalTrades}</span>
                </div>
                <span>No winners in the<br/>last {perfMetrics.totalTrades} closed trades.</span>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <DonutChart percentage={perfMetrics.winRate} />
                <span className="text-xs text-text-muted">Win Rate</span>
              </div>
            )}
          </MetricCard>
        </div>

        {/* Section 2: Portfolio Overview — items-start so the left chart
            panel doesn't stretch to match the (much taller) right column
            when the allocation list has many holdings. */}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-5 xl:gap-5">
          {/* Left: Equity Curve Chart — col-span-2 (was 3) so the right
              column gets more breathing room for the Allocation +
              Performance widgets. Height also dropped a bit. */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.3 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5 lg:col-span-2"
          >
            <div className="mb-4">
              <h2 className="text-base font-semibold text-text-primary">Portfolio Equity</h2>
              <p className="text-xs text-text-muted">Paper account performance over time</p>
            </div>
            {equityCurve.length === 0 ? (
              <div className="flex h-[240px] xl:h-[280px] flex-col items-center justify-center gap-2 text-center text-text-muted">
                <p className="text-sm">No equity history yet</p>
                <p className="text-xs">Snapshots accumulate once the engine has been running for a few minutes.</p>
              </div>
            ) : (
            <div className="h-[240px] xl:h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityCurve} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#06B6D4" stopOpacity={0.15} />
                      <stop offset="100%" stopColor="#06B6D4" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" strokeOpacity={0.3} vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fill: '#64748B', fontSize: 12, fontFamily: 'JetBrains Mono, ui-monospace, monospace' }}
                    axisLine={{ stroke: '#1E293B' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: '#64748B', fontSize: 12, fontFamily: 'JetBrains Mono, ui-monospace, monospace' }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                    domain={['dataMin - 2000', 'dataMax + 2000']}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1A2235',
                      border: '1px solid #1E293B',
                      borderRadius: '8px',
                      fontFamily: 'JetBrains Mono, ui-monospace, monospace',
                      fontSize: '12px',
                      color: '#F8FAFC',
                    }}
                    formatter={(value: number) => [formatCurrency(value), 'Equity']}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="#06B6D4"
                    strokeWidth={2}
                    fill="url(#equityGradient)"
                    animationDuration={1200}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            )}
          </motion.div>

          {/* Right: Allocation + Key Stats */}
          <div className="flex flex-col gap-4 lg:col-span-3">
            {/* Asset Allocation */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.4 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
            >
              <h3 className="text-sm font-semibold text-text-primary">Allocation</h3>
              {allocList.length === 0 ? (
                <p className="mt-3 text-xs text-text-muted">No positions yet.</p>
              ) : (
              <div className="mt-3 flex items-center gap-4">
                <div className="h-[140px] w-[140px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={allocList}
                        cx="50%"
                        cy="50%"
                        innerRadius={40}
                        outerRadius={65}
                        dataKey="value"
                        stroke="none"
                        animationBegin={0}
                        animationDuration={800}
                      >
                        {allocList.map((entry) => (
                          <Cell key={entry.name} fill={entry.color} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="grid flex-1 grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-3">
                  {allocList.map((asset) => (
                    <div key={asset.name} className="flex items-center gap-1.5">
                      <div className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: asset.color }} />
                      <span className="text-xs text-text-secondary truncate">{asset.name}</span>
                      <span className="ml-auto text-xs font-mono text-text-primary">{asset.value}%</span>
                    </div>
                  ))}
                </div>
              </div>
              )}
            </motion.div>

            {/* Key Performance Stats */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.5 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
            >
              <h3 className="text-sm font-semibold text-text-primary mb-3">Key Performance Stats</h3>
              <div className="grid grid-cols-2 gap-3">
                <div className="border-b border-border-subtle pb-2">
                  <p className="text-xs text-text-muted">Sharpe Ratio</p>
                  <p className="font-mono text-sm text-text-primary">{fmtMetric(perfMetrics.sharpeRatio)}</p>
                </div>
                <div className="border-b border-border-subtle pb-2">
                  <p className="text-xs text-text-muted">Max Drawdown</p>
                  <p className="font-mono text-sm text-danger-red">{fmtMetric(perfMetrics.maxDrawdownPercent, 1, '%')}</p>
                </div>
                <div className="border-b border-border-subtle pb-2">
                  <p className="text-xs text-text-muted">Profit Factor</p>
                  <p className="font-mono text-sm text-success-green">{fmtMetric(perfMetrics.profitFactor)}</p>
                </div>
                <div className="border-b-0 pb-0">
                  <p className="text-xs text-text-muted">Total Trades</p>
                  <p className="font-mono text-sm text-text-primary">{perfMetrics.totalTrades}</p>
                </div>
              </div>
              {perfMetrics.totalTrades === 0 && (
                <p className="mt-2 text-[11px] text-text-muted">Stats fill in after the first closed trades.</p>
              )}
            </motion.div>
          </div>
        </div>

        {/* Section 3: Active Bots */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.5 }}
        >
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-text-primary">Active Bots</h2>
              <Badge variant={runningCount > 0 ? 'success' : 'neutral'}>
                {runningCount} running
              </Badge>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigate('/bots')}
                className="text-sm text-accent-cyan hover:underline"
              >
                View All
              </button>
              <button
                onClick={() => navigate('/bots')}
                className="flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
              >
                <Plus className="h-3.5 w-3.5" />
                New Bot
              </button>
            </div>
          </div>

          {strategies.length === 0 ? (
            <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-8 text-center text-sm text-text-muted">
              No bots yet.{' '}
              <button
                onClick={() => navigate('/bots')}
                className="text-accent-cyan hover:underline"
              >
                Create one in Bot Lab
              </button>
              .
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {/* Order: is_active first, then by total_trades desc — surfaces
                  bots that are actually doing something instead of the
                  arbitrary registration order. */}
              {[...strategies]
                .sort((a, b) => {
                  if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
                  const at = Number(((a.metrics as Record<string, number>) || {}).total_trades ?? 0);
                  const bt = Number(((b.metrics as Record<string, number>) || {}).total_trades ?? 0);
                  return bt - at;
                })
                .slice(0, 4)
                .map((bot, index) => {
                const metrics = bot.metrics as Record<string, number> | null;
                const pnl = Number(metrics?.total_pnl ?? 0);
                const cfg = (bot.config as Record<string, unknown>) || {};
                // Multi-symbol bots store symbols in ``config.symbols`` (array);
                // single-symbol legacy bots use ``config.symbol``. Show first 3
                // + "+N more" so the card width stays clean.
                const symList = Array.isArray(cfg.symbols)
                  ? (cfg.symbols as string[])
                  : (cfg.symbol ? [String(cfg.symbol)] : []);
                const pairDisplay =
                  symList.length === 0 ? '—'
                  : symList.length <= 3 ? symList.join(', ')
                  : `${symList.slice(0, 3).join(', ')} +${symList.length - 3}`;
                const status: 'running' | 'paused' = bot.is_active ? 'running' : 'paused';
                return (
                  <motion.div
                    key={bot.strategy_id}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.3,
                      delay: 0.6 + index * 0.1,
                      ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
                    }}
                    className="rounded-[10px] border border-border-subtle bg-bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-accent-cyan/20"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <Badge variant="cyan">{bot.strategy_type}</Badge>
                        <p
                          className="mt-2 font-mono text-xs text-text-primary truncate"
                          title={symList.join(', ')}
                        >
                          {pairDisplay}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <StatusDot status={status} />
                        <span
                          className={`text-xs ${
                            status === 'running' ? 'text-success-green' : 'text-warning-amber'
                          }`}
                        >
                          {status === 'running' ? 'Running' : 'Paused'}
                        </span>
                      </div>
                    </div>

                    <div className="mt-3">
                      <p
                        className={`font-mono text-base font-medium tabular-nums ${
                          pnl >= 0 ? 'text-success-green' : 'text-danger-red'
                        }`}
                      >
                        {pnl >= 0 ? '+' : ''}
                        {formatCurrency(pnl)}
                      </p>
                      <p className="text-xs text-text-muted">
                        {metrics?.total_trades ? `${metrics.total_trades} trades` : 'No trades yet'}
                      </p>
                    </div>

                    <div className="mt-3 flex items-center gap-2">
                      <button
                        onClick={() => handleToggleBot(bot.strategy_id, bot.is_active)}
                        aria-label={bot.is_active ? 'Pause bot' : 'Resume bot'}
                        className={`rounded-md p-1.5 transition-colors ${
                          bot.is_active
                            ? 'text-warning-amber hover:bg-warning-amber/10'
                            : 'text-success-green hover:bg-success-green/10'
                        }`}
                      >
                        {bot.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button
                        onClick={() => navigate('/bots')}
                        aria-label="Bot settings"
                        className="rounded-md p-1.5 text-text-secondary hover:bg-bg-input hover:text-text-primary transition-colors"
                      >
                        <Settings className="h-4 w-4" />
                      </button>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </motion.div>

        {/* Section 4: Market Ticker Tape */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.7 }}
          className="overflow-hidden rounded-[10px] border border-border-subtle bg-bg-surface"
        >
          <div className="flex h-12 items-center">
            <div className="animate-marquee flex items-center whitespace-nowrap hover:[animation-play-state:paused]">
              {[...tickers, ...tickers].map((ticker, i) => (
                <div
                  key={`${ticker.symbol}-${i}`}
                  className="flex items-center gap-2 px-4"
                >
                  <span className="text-xs font-medium text-text-muted">{ticker.symbol}</span>
                  <span className="font-mono text-xs text-text-primary">
                    ${ticker.price.toLocaleString('en-US', { minimumFractionDigits: ticker.price < 1 ? 4 : 2, maximumFractionDigits: ticker.price < 1 ? 4 : 2 })}
                  </span>
                  <span
                    className={`font-mono text-xs tabular-nums ${
                      ticker.change24hPercent >= 0 ? 'text-success-green' : 'text-danger-red'
                    }`}
                  >
                    {ticker.change24hPercent >= 0 ? '+' : ''}
                    {ticker.change24hPercent.toFixed(2)}%
                  </span>
                  <div className="mx-2 h-4 w-px bg-border-subtle" />
                </div>
              ))}
            </div>
          </div>
        </motion.div>

        {/* Section 5: Recent Activity */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:gap-5">
          {/* Recent Trades */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.8 }}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-text-primary">Recent Trades</h2>
              <button
                onClick={() => navigate('/analytics')}
                className="text-sm text-accent-cyan hover:underline"
              >
                View All
              </button>
            </div>
            <DataTable
              columns={tradeColumns}
              data={trades.slice(0, 5).length ? trades.slice(0, 5) : []}
              keyExtractor={(row) => row.id}
            />
          </motion.div>

          {/* System Alerts */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.85 }}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-text-primary">System Alerts</h2>
              <button className="text-xs text-text-secondary hover:text-text-primary transition-colors">
                Clear All
              </button>
            </div>
            <div className="space-y-2">
              {alerts.length === 0 && (
                <div className="rounded-lg border border-border-subtle bg-bg-surface p-3 text-xs text-text-muted">
                  No recent activity.
                </div>
              )}
              {alerts.map((alert, index) => (
                <motion.div
                  key={alert.id}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{
                    duration: 0.3,
                    delay: 0.9 + index * 0.08,
                    ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
                  }}
                  className={`flex items-start gap-3 rounded-lg border border-border-subtle bg-bg-surface p-3 border-l-[3px] ${alertBorderMap[alert.severity]}`}
                >
                  {alertIconMap[alert.icon]}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary truncate">{alert.message}</p>
                    <p className="mt-0.5 text-xs text-text-muted">{alert.timestamp}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </div>
      </div>
    </Layout>
  );
}
