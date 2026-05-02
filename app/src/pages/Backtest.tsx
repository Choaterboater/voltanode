import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Play,
  BarChart3,
} from 'lucide-react';
import Layout from '@/components/Layout';
import { runBacktest, type BacktestPayload } from '@/lib/api';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface BacktestResult {
  backtest_id: string;
  strategy_id: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  equity_curve: { equity: number; timestamp?: string }[];
}

export default function Backtest() {
  const [strategyType, setStrategyType] = useState('Momentum');
  const [symbol, setSymbol] = useState('BTC-USD');
  const [timeframe, setTimeframe] = useState('1d');
  const [initialBalance, setInitialBalance] = useState('10000');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    try {
      setRunning(true);
      setError(null);
      setResult(null);

      const payload: BacktestPayload = {
        strategy_id: strategyType,
        symbol,
        asset_class: 'crypto',
        timeframe,
        start_date: '2024-01-01',
        end_date: '2024-04-01',
        initial_balance: { USDT: parseFloat(initialBalance) },
      };

      const res = await runBacktest(payload);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backtest failed');
    } finally {
      setRunning(false);
    }
  }

  const formatCurrency = (v: number) =>
    `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <Layout title="Backtest Lab">
      <div className="space-y-5">
        {error && (
          <div className="rounded-lg border border-danger-red/30 bg-danger-red/10 px-4 py-2 text-sm text-danger-red">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 xl:gap-5">
          {/* Config Panel */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
          >
            <h2 className="mb-4 text-base font-semibold text-text-primary">Backtest Config</h2>
            <form onSubmit={handleRun} className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-text-muted">Strategy</label>
                <select
                  value={strategyType}
                  onChange={(e) => setStrategyType(e.target.value)}
                  className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                >
                  <option value="Momentum">Momentum</option>
                  <option value="MeanReversion">Mean Reversion</option>
                  <option value="Grid">Grid</option>
                  <option value="Breakout">Breakout</option>
                  <option value="MACD">MACD</option>
                  <option value="Arbitrage">Arbitrage</option>
                  <option value="EnsembleML">ML Ensemble</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">Symbol</label>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                />
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">Timeframe</label>
                <select
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                >
                  <option value="1h">1 Hour</option>
                  <option value="4h">4 Hour</option>
                  <option value="1d">1 Day</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">Initial Balance (USDT)</label>
                <input
                  type="number"
                  value={initialBalance}
                  onChange={(e) => setInitialBalance(e.target.value)}
                  className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                />
              </div>

              <button
                type="submit"
                disabled={running}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-accent-cyan py-2.5 text-sm font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
              >
                {running ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Run Backtest
              </button>
            </form>
          </motion.div>

          {/* Results */}
          <div className="space-y-4 lg:col-span-2">
            {result ? (
              <>
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="grid grid-cols-2 gap-3 sm:grid-cols-3"
                >
                  <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                    <p className="text-xs text-text-muted">Total Return</p>
                    <p
                      className={`mt-1 font-mono text-lg ${
                        result.total_return_pct >= 0 ? 'text-success-green' : 'text-danger-red'
                      }`}
                    >
                      {result.total_return_pct >= 0 ? '+' : ''}
                      {result.total_return_pct.toFixed(2)}%
                    </p>
                  </div>
                  <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                    <p className="text-xs text-text-muted">Sharpe Ratio</p>
                    <p className="mt-1 font-mono text-lg text-text-primary">
                      {result.sharpe_ratio.toFixed(2)}
                    </p>
                  </div>
                  <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                    <p className="text-xs text-text-muted">Max Drawdown</p>
                    <p className="mt-1 font-mono text-lg text-danger-red">
                      {result.max_drawdown_pct.toFixed(2)}%
                    </p>
                  </div>
                  <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                    <p className="text-xs text-text-muted">Win Rate</p>
                    <p className="mt-1 font-mono text-lg text-text-primary">
                      {result.win_rate.toFixed(1)}%
                    </p>
                  </div>
                  <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                    <p className="text-xs text-text-muted">Profit Factor</p>
                    <p className="mt-1 font-mono text-lg text-text-primary">
                      {result.profit_factor.toFixed(2)}
                    </p>
                  </div>
                  <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                    <p className="text-xs text-text-muted">Total Trades</p>
                    <p className="mt-1 font-mono text-lg text-text-primary">
                      {result.total_trades}
                    </p>
                  </div>
                </motion.div>

                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.1 }}
                  className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
                >
                  <h3 className="mb-3 text-sm font-semibold text-text-primary">Equity Curve</h3>
                  <div className="h-[300px] xl:h-[380px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={result.equity_curve.map((p, i) => ({
                          ...p,
                          day: `Day ${i + 1}`,
                        }))}
                        margin={{ top: 5, right: 10, left: 0, bottom: 0 }}
                      >
                        <defs>
                          <linearGradient id="btGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#06B6D4" stopOpacity={0.15} />
                            <stop offset="100%" stopColor="#06B6D4" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" strokeOpacity={0.3} vertical={false} />
                        <XAxis dataKey="day" tick={{ fill: '#64748B', fontSize: 12 }} axisLine={{ stroke: '#1E293B' }} tickLine={false} />
                        <YAxis tick={{ fill: '#64748B', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: '#1A2235',
                            border: '1px solid #1E293B',
                            borderRadius: '8px',
                            fontSize: '12px',
                            color: '#F8FAFC',
                          }}
                          formatter={(value: number) => [formatCurrency(value), 'Equity']}
                        />
                        <Area type="monotone" dataKey="equity" stroke="#06B6D4" strokeWidth={2} fill="url(#btGradient)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </motion.div>
              </>
            ) : (
              <div className="flex h-64 items-center justify-center rounded-[10px] border border-border-subtle bg-bg-surface">
                <div className="text-center">
                  <BarChart3 className="mx-auto mb-2 h-8 w-8 text-text-muted" />
                  <p className="text-sm text-text-muted">Configure and run a backtest to see results</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
