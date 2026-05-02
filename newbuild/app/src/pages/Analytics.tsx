import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Target,
  Calendar,
  Loader2,
} from 'lucide-react';
import Layout from '@/components/Layout';
import { useTrades } from '@/hooks/useApi';

interface AnalyticsData {
  total_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  total_pnl: number;
  daily_pnl: { date: string; pnl: number }[];
  symbols: { symbol: string; trades: number; pnl: number }[];
}

export default function Analytics() {
  const { data: trades, loading, refresh } = useTrades();
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [range, setRange] = useState<'7d' | '30d' | '90d' | 'all'>('30d');

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!trades.length) {
      // Demo data
      setAnalytics({
        total_trades: 142,
        win_rate: 58.4,
        avg_win: 342.5,
        avg_loss: -189.2,
        profit_factor: 1.87,
        total_pnl: 8743.2,
        daily_pnl: [
          { date: 'Mon', pnl: 450 },
          { date: 'Tue', pnl: -120 },
          { date: 'Wed', pnl: 890 },
          { date: 'Thu', pnl: 230 },
          { date: 'Fri', pnl: -340 },
          { date: 'Sat', pnl: 120 },
          { date: 'Sun', pnl: 560 },
        ],
        symbols: [
          { symbol: 'BTC/USD', trades: 45, pnl: 4520 },
          { symbol: 'ETH/USD', trades: 38, pnl: 2100 },
          { symbol: 'SOL/USD', trades: 32, pnl: -890 },
          { symbol: 'AVAX/USD', trades: 27, pnl: 3013 },
        ],
      });
      return;
    }

    const wins = trades.filter((t) => (t.realized_pnl || 0) > 0);
    const losses = trades.filter((t) => (t.realized_pnl || 0) < 0);
    const winRate = trades.length > 0 ? (wins.length / trades.length) * 100 : 0;
    const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + (t.realized_pnl || 0), 0) / wins.length : 0;
    const avgLoss = losses.length > 0 ? losses.reduce((s, t) => s + (t.realized_pnl || 0), 0) / losses.length : 0;
    const totalPnl = trades.reduce((s, t) => s + (t.realized_pnl || 0), 0);

    setAnalytics({
      total_trades: trades.length,
      win_rate: winRate,
      avg_win: avgWin,
      avg_loss: avgLoss,
      profit_factor: Math.abs(avgLoss) > 0 ? Math.abs(avgWin / avgLoss) : 0,
      total_pnl: totalPnl,
      daily_pnl: [],
      symbols: [],
    });
  }, [trades]);

  const ranges: { label: string; value: '7d' | '30d' | '90d' | 'all' }[] = [
    { label: '7D', value: '7d' },
    { label: '30D', value: '30d' },
    { label: '90D', value: '90d' },
    { label: 'All', value: 'all' },
  ];

  if (loading) {
    return (
      <Layout title="Analytics">
        <div className="flex h-96 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-accent-cyan" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Analytics">
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Range selector */}
        <div className="flex items-center gap-1">
          {ranges.map((r) => (
            <button
              key={r.value}
              onClick={() => setRange(r.value)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                range === r.value
                  ? 'bg-accent-cyan text-text-inverse'
                  : 'text-text-muted hover:bg-bg-elevated hover:text-text-secondary'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: 'Total P&L', value: analytics ? `$${analytics.total_pnl.toLocaleString()}` : '$0', color: (analytics?.total_pnl || 0) >= 0 ? 'text-success-green' : 'text-danger-red', icon: TrendingUp },
            { label: 'Win Rate', value: analytics ? `${analytics.win_rate.toFixed(1)}%` : '0%', color: 'text-text-primary', icon: Target },
            { label: 'Profit Factor', value: analytics ? analytics.profit_factor.toFixed(2) : '0', color: 'text-text-primary', icon: BarChart3 },
            { label: 'Trades', value: analytics ? String(analytics.total_trades) : '0', color: 'text-text-primary', icon: Calendar },
          ].map((m, i) => (
            <motion.div key={m.label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
              <div className="flex items-center gap-2">
                <m.icon className="h-4 w-4 text-text-muted" />
                <p className="text-xs text-text-muted">{m.label}</p>
              </div>
              <p className={`mt-2 font-mono text-xl font-semibold ${m.color}`}>{m.value}</p>
            </motion.div>
          ))}
        </div>

        {/* Avg Win/Loss */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-success-green" />
              <p className="text-xs text-text-muted">Avg Win</p>
            </div>
            <p className="mt-2 font-mono text-xl font-semibold text-success-green">
              +${analytics?.avg_win.toFixed(2) || '0.00'}
            </p>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <div className="flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-danger-red" />
              <p className="text-xs text-text-muted">Avg Loss</p>
            </div>
            <p className="mt-2 font-mono text-xl font-semibold text-danger-red">
              ${analytics?.avg_loss.toFixed(2) || '0.00'}
            </p>
          </motion.div>
        </div>

        {/* Symbol Breakdown */}
        {analytics?.symbols && analytics.symbols.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-3">Performance by Symbol</h3>
            <table className="w-full text-left text-xs">
              <thead className="bg-bg-input text-text-muted">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Trades</th>
                  <th className="px-3 py-2 text-right">P&L</th>
                </tr>
              </thead>
              <tbody className="text-text-secondary">
                {analytics.symbols.map((s) => (
                  <tr key={s.symbol} className="border-t border-border-subtle">
                    <td className="px-3 py-2 font-medium text-text-primary">{s.symbol}</td>
                    <td className="px-3 py-2">{s.trades}</td>
                    <td className={`px-3 py-2 text-right font-mono ${s.pnl >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
                      {s.pnl >= 0 ? '+' : ''}${s.pnl.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </motion.div>
        )}
      </div>
    </Layout>
  );
}
