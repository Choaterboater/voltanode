import { useState } from 'react';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import { useDashboardData } from '@/hooks/useDashboard';
import { toggleStrategy, type ApiStrategy } from '@/lib/api';
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
import {
  performanceMetrics,
  assetAllocation,
  equityCurveData,
  alerts,
  balanceSparkline,
  pnlSparkline,
} from '@/data/mockData';

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

export default function Home() {
  const [selectedRange, setSelectedRange] = useState('30D');
  const [notificationCount] = useState(3);
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
  } = useDashboardData();

  async function handleToggleBot(id: string, current: boolean) {
    try {
      await toggleStrategy(id, !current);
      await refetch?.();
    } catch {
      // Silently ignore — error surfaces via dashboard error state on next poll.
    }
  }

  const runningCount = strategies.filter((s: ApiStrategy) => s.is_active).length;

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
        <span
          className={`font-mono text-sm tabular-nums ${
            row.pnl >= 0 ? 'text-success-green' : 'text-danger-red'
          }`}
        >
          {row.pnl >= 0 ? '+' : ''}
          {formatCurrency(row.pnl)}
        </span>
      ),
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
            <MiniSparkline data={balanceSparkline} color="#10B981" />
          </MetricCard>

          <MetricCard
            label="Unrealized P&L"
            value={`${portfolio.dailyPnl >= 0 ? '+' : ''}${formatCurrency(portfolio.dailyPnl)}`}
            delta={`${portfolio.dailyPnlPercent.toFixed(2)}%`}
            deltaPositive={portfolio.dailyPnl >= 0}
            icon={<TrendingUp className="h-5 w-5 text-success-green" />}
            delay={0.08}
          >
            <MiniSparkline data={pnlSparkline} color="#10B981" />
          </MetricCard>

          <MetricCard
            label="Active Positions"
            value={`${totalPos}`}
            delta={`${longCount} long / ${shortCount} short`}
            deltaPositive={true}
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
            value={formatPercent(performanceMetrics.winRate)}
            delta="+5.2% vs last month"
            deltaPositive={true}
            icon={<Target className="h-5 w-5" />}
            delay={0.24}
          >
            <div className="flex items-center gap-3">
              <DonutChart percentage={performanceMetrics.winRate} />
              <span className="text-xs text-text-muted">Win Rate</span>
            </div>
          </MetricCard>
        </div>

        {/* Section 2: Portfolio Overview */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5 xl:gap-5">
          {/* Left: Equity Curve Chart */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.3 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5 lg:col-span-3"
          >
            <div className="mb-4">
              <h2 className="text-base font-semibold text-text-primary">Portfolio Equity</h2>
              <p className="text-xs text-text-muted">Paper account performance over time</p>
            </div>
            <div className="h-[320px] xl:h-[380px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityCurveData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
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
          </motion.div>

          {/* Right: Allocation + Key Stats */}
          <div className="flex flex-col gap-4 lg:col-span-2">
            {/* Asset Allocation */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.4 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
            >
              <h3 className="text-sm font-semibold text-text-primary">Allocation</h3>
              <div className="mt-3 flex items-center gap-4">
                <div className="h-[140px] w-[140px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={assetAllocation}
                        cx="50%"
                        cy="50%"
                        innerRadius={40}
                        outerRadius={65}
                        dataKey="percentage"
                        stroke="none"
                        animationBegin={0}
                        animationDuration={800}
                      >
                        {assetAllocation.map((entry) => (
                          <Cell key={entry.symbol} fill={entry.color} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-2">
                  {assetAllocation.map((asset) => (
                    <div key={asset.symbol} className="flex items-center gap-2">
                      <div className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: asset.color }} />
                      <span className="text-xs text-text-secondary w-10">{asset.symbol}</span>
                      <span className="text-xs font-mono text-text-primary">{asset.percentage}%</span>
                    </div>
                  ))}
                </div>
              </div>
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
                  <p className="font-mono text-sm text-text-primary">{performanceMetrics.sharpeRatio.toFixed(2)}</p>
                </div>
                <div className="border-b border-border-subtle pb-2">
                  <p className="text-xs text-text-muted">Max Drawdown</p>
                  <p className="font-mono text-sm text-danger-red">{performanceMetrics.maxDrawdownPercent.toFixed(1)}%</p>
                </div>
                <div className="border-b border-border-subtle pb-2">
                  <p className="text-xs text-text-muted">Profit Factor</p>
                  <p className="font-mono text-sm text-success-green">{performanceMetrics.profitFactor.toFixed(2)}</p>
                </div>
                <div className="border-b-0 pb-0">
                  <p className="text-xs text-text-muted">Trades / Day</p>
                  <p className="font-mono text-sm text-text-primary">{performanceMetrics.tradesPerDay.toFixed(1)}</p>
                </div>
              </div>
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
              {strategies.slice(0, 4).map((bot, index) => {
                const metrics = bot.metrics as Record<string, number> | null;
                const pnl = Number(metrics?.total_pnl ?? 0);
                const pair = String((bot.config as Record<string, unknown>)?.symbol ?? '—');
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
                    <div className="flex items-start justify-between">
                      <div>
                        <Badge variant="cyan">{bot.strategy_type}</Badge>
                        <p className="mt-2 font-mono text-sm text-text-primary">{pair}</p>
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
