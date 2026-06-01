import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3,
  TrendingUp,
  Target,
  Activity,
  Download,
} from 'lucide-react';
import Layout from '@/components/Layout';
import DataTable from '@/components/DataTable';
import Badge from '@/components/Badge';
import {
  getPortfolio,
  getTrades,
  getStrategies,
  type ApiPortfolio,
  type ApiTrade,
  type ApiStrategy,
} from '@/lib/api';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';

interface TradeSummary {
  totalTrades: number;
  winCount: number;
  lossCount: number;
  winRate: number;
  totalPnl: number;
  avgWin: number;
  avgLoss: number;
  bestTrade: number;
  worstTrade: number;
}

function computeSummary(trades: ApiTrade[]): TradeSummary {
  if (trades.length === 0) {
    return {
      totalTrades: 0,
      winCount: 0,
      lossCount: 0,
      winRate: 0,
      totalPnl: 0,
      avgWin: 0,
      avgLoss: 0,
      bestTrade: 0,
      worstTrade: 0,
    };
  }
  // Only count CLOSED trades (realized_pnl set) toward win/loss/win-rate.
  // Open BUYs land with realized_pnl=null and previously inflated the
  // "Breakeven" bucket of the win/loss pie.
  const closed = trades.filter((t) => t.realized_pnl != null);
  const wins = closed.filter((t) => (t.realized_pnl ?? 0) > 0);
  const losses = closed.filter((t) => (t.realized_pnl ?? 0) < 0);
  const pnls = closed.map((t) => t.realized_pnl ?? 0);
  return {
    totalTrades: trades.length,
    winCount: wins.length,
    lossCount: losses.length,
    winRate: closed.length > 0 ? (wins.length / closed.length) * 100 : 0,
    totalPnl: pnls.reduce((a, b) => a + b, 0),
    avgWin: wins.length > 0 ? wins.reduce((s, t) => s + (t.realized_pnl ?? 0), 0) / wins.length : 0,
    avgLoss: losses.length > 0 ? losses.reduce((s, t) => s + (t.realized_pnl ?? 0), 0) / losses.length : 0,
    bestTrade: Math.max(...pnls),
    worstTrade: Math.min(...pnls),
  };
}

export default function Analytics() {
  const [, setPortfolio] = useState<ApiPortfolio | null>(null);
  const [trades, setTrades] = useState<ApiTrade[]>([]);
  const [strategies, setStrategies] = useState<ApiStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      setLoading(true);
      const [p, t, s] = await Promise.all([getPortfolio(), getTrades(), getStrategies()]);
      setPortfolio(p);
      // /trades/ returns oldest-first; sort newest-first for the Trade
      // History table. Same fix as useDashboard.mapTrades.
      const sorted = [...t].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      );
      setTrades(sorted);
      setStrategies(s.strategies);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }

  const summary = computeSummary(trades);
  const formatCurrency = (v: number) =>
    `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  // Smart price formatter that handles micro-cap crypto prices (SHIB ~6e-6).
  // Stops displaying ``$0.0000`` for things like SHIB / PEPE.
  const formatPrice = (v: number): string => {
    if (v == null || !isFinite(v)) return '—';
    if (Math.abs(v) >= 1) return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (Math.abs(v) >= 0.01) return `$${v.toFixed(4)}`;
    if (Math.abs(v) > 0) return `$${v.toExponential(2)}`;
    return '$0.00';
  };

  const tradeColumns = [
    {
      key: 'time',
      header: 'Time',
      render: (row: ApiTrade) => (
        <span className="font-mono text-xs text-text-muted">
          {new Date(row.timestamp).toLocaleString()}
        </span>
      ),
    },
    {
      key: 'symbol',
      header: 'Symbol',
      render: (row: ApiTrade) => (
        <span className="font-mono text-sm text-text-primary">{row.symbol.replace('-', '/')}</span>
      ),
    },
    {
      key: 'side',
      header: 'Side',
      render: (row: ApiTrade) => {
        // Backend serializes 'buy' / 'sell' lowercase; the old strict
        // 'BUY' compare painted every row red.
        const side = String(row.side ?? '').toLowerCase();
        return (
          <Badge variant={side === 'buy' ? 'success' : 'danger'}>
            {side.toUpperCase()}
          </Badge>
        );
      },
    },
    {
      key: 'qty',
      header: 'Qty',
      render: (row: ApiTrade) => (
        <span className="font-mono text-sm text-text-primary">{row.quantity}</span>
      ),
    },
    {
      key: 'price',
      header: 'Price',
      render: (row: ApiTrade) => (
        <span className="font-mono text-sm text-text-primary">{formatPrice(row.price)}</span>
      ),
    },
    {
      key: 'fee',
      header: 'Fee',
      render: (row: ApiTrade) => (
        <span className="font-mono text-sm text-text-muted">{formatCurrency(row.fee)}</span>
      ),
    },
    {
      key: 'pnl',
      header: 'P&L',
      render: (row: ApiTrade) => {
        const pnl = row.realized_pnl ?? 0;
        return (
          <span className={`font-mono text-sm ${pnl >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
            {pnl >= 0 ? '+' : ''}
            {formatCurrency(pnl)}
          </span>
        );
      },
    },
    {
      key: 'strategy',
      header: 'Strategy',
      render: (row: ApiTrade) => (
        <span className="text-xs text-text-muted">{row.strategy_id ?? 'Manual'}</span>
      ),
    },
  ];

  // Group trades by symbol for the bar chart
  const tradesBySymbol = trades.reduce(
    (acc, t) => {
      const sym = t.symbol.replace('-', '/');
      if (!acc[sym]) acc[sym] = 0;
      acc[sym] += t.realized_pnl ?? 0;
      return acc;
    },
    {} as Record<string, number>
  );
  const barData = Object.entries(tradesBySymbol).map(([symbol, pnl]) => ({ symbol, pnl }));

  // Win/Loss pie data — split into wins / losses / breakeven (closed at $0)
  // and a separate "Open" bucket for trades still without a realized P&L.
  const closedCount = summary.winCount + summary.lossCount;
  const breakevenCount = trades.filter((t) => t.realized_pnl === 0).length;
  const openCount = trades.filter((t) => t.realized_pnl == null).length;
  const pieData = [
    { name: 'Wins', value: summary.winCount, color: '#10B981' },
    { name: 'Losses', value: summary.lossCount, color: '#EF4444' },
    { name: 'Breakeven', value: breakevenCount, color: '#64748B' },
    { name: 'Open', value: openCount, color: '#0EA5E9' },
  ].filter((d) => d.value > 0);
  void closedCount;

  if (loading) {
    return (
      <Layout title="Analytics">
        <div className="flex h-64 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-cyan border-t-transparent" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Analytics">
      <div className="space-y-5">
        {error && (
          <div className="rounded-lg border border-danger-red/30 bg-danger-red/10 px-4 py-2 text-sm text-danger-red">
            {error}
          </div>
        )}

        {/* Metric Cards */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 xl:gap-5">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
          >
            <div className="flex items-center gap-2 text-text-muted">
              <Activity className="h-4 w-4" />
              <span className="text-xs">Total Trades</span>
            </div>
            <p className="mt-1 font-mono text-xl text-text-primary">{summary.totalTrades}</p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
          >
            <div className="flex items-center gap-2 text-text-muted">
              <Target className="h-4 w-4" />
              <span className="text-xs">Win Rate</span>
            </div>
            <p className="mt-1 font-mono text-xl text-text-primary">{summary.winRate.toFixed(1)}%</p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
          >
            <div className="flex items-center gap-2 text-text-muted">
              <TrendingUp className="h-4 w-4" />
              <span className="text-xs">Total P&L</span>
            </div>
            <p className={`mt-1 font-mono text-xl ${summary.totalPnl >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
              {summary.totalPnl >= 0 ? '+' : ''}
              {formatCurrency(summary.totalPnl)}
            </p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
          >
            <div className="flex items-center gap-2 text-text-muted">
              <BarChart3 className="h-4 w-4" />
              <span className="text-xs">Strategies Active</span>
            </div>
            <p className="mt-1 font-mono text-xl text-text-primary">
              {strategies.filter((s) => s.is_active).length}
            </p>
          </motion.div>
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:gap-5">
          {/* P&L by Symbol */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
          >
            <h3 className="mb-3 text-sm font-semibold text-text-primary">P&L by Symbol</h3>
            {barData.length === 0 ? (
              <div className="flex h-48 items-center justify-center text-sm text-text-muted">
                No trade data yet
              </div>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" strokeOpacity={0.3} vertical={false} />
                    <XAxis dataKey="symbol" tick={{ fill: '#64748B', fontSize: 12 }} axisLine={{ stroke: '#1E293B' }} tickLine={false} />
                    <YAxis tick={{ fill: '#64748B', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1A2235', border: '1px solid #1E293B', borderRadius: '8px', fontSize: '12px', color: '#F8FAFC' }}
                      formatter={(value: number) => [formatCurrency(value), 'P&L']}
                    />
                    <Bar dataKey="pnl" fill="#06B6D4" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </motion.div>

          {/* Win/Loss Distribution */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.25 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
          >
            <h3 className="mb-3 text-sm font-semibold text-text-primary">Win / Loss Distribution</h3>
            {pieData.length === 0 ? (
              <div className="flex h-48 items-center justify-center text-sm text-text-muted">
                No trade data yet
              </div>
            ) : (
              <div className="flex h-64 items-center justify-center gap-8">
                <div className="h-48 w-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} cx="50%" cy="50%" innerRadius={40} outerRadius={70} dataKey="value" stroke="none">
                        {pieData.map((entry) => (
                          <Cell key={entry.name} fill={entry.color} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2">
                  {pieData.map((d) => (
                    <div key={d.name} className="flex items-center gap-2">
                      <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: d.color }} />
                      <span className="text-sm text-text-secondary">{d.name}</span>
                      <span className="font-mono text-sm text-text-primary">{d.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        </div>

        {/* Trade History Table */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Trade History</h3>
            <button
              onClick={() => window.open('/api/trades/export?format=csv', '_blank')}
              className="flex items-center gap-1.5 rounded-md bg-bg-input px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </button>
          </div>
          {trades.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-sm text-text-muted">
              No trades recorded yet. Place an order in Paper Trading to generate history.
            </div>
          ) : (
            <DataTable columns={tradeColumns} data={trades} keyExtractor={(row) => row.id} />
          )}
        </motion.div>

        {/* Strategy Performance */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.35 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h3 className="mb-3 text-sm font-semibold text-text-primary">Strategy Performance</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {strategies.map((s) => {
              const metrics = s.metrics as Record<string, number> | null;
              return (
                <div key={s.strategy_id} className="rounded-lg border border-border-subtle bg-bg-base p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-text-primary">{s.strategy_type}</span>
                    <Badge variant={s.is_active ? 'success' : 'neutral'}>
                      {s.is_active ? 'Active' : 'Idle'}
                    </Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <p className="text-text-muted">Trades</p>
                      <p className="font-mono text-text-primary">{metrics?.total_trades ?? 0}</p>
                    </div>
                    <div>
                      <p className="text-text-muted">Win Rate</p>
                      <p className="font-mono text-text-primary">
                        {metrics?.win_rate ? `${metrics.win_rate.toFixed(1)}%` : '-'}
                      </p>
                    </div>
                    <div>
                      <p className="text-text-muted">P&L</p>
                      <p className={`font-mono ${(metrics?.total_pnl ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
                        {metrics?.total_pnl ? formatCurrency(metrics.total_pnl) : '-'}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </motion.div>
      </div>
    </Layout>
  );
}
