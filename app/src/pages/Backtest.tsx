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

// Strategy IDs MUST match the snake_case identifiers returned by
// /strategies/available — the prior PascalCase values (Momentum, MACD,
// MeanReversion) silently failed to resolve on the backend.
// auto_discovery + squeeze are excluded because they depend on
// runtime data sources (Watchlist, SEC EDGAR, FINRA) that aren't
// available in a backtest replay.
const BACKTESTABLE_STRATEGIES: { id: string; label: string }[] = [
  { id: 'momentum', label: 'Momentum' },
  { id: 'mean_reversion', label: 'Mean Reversion' },
  { id: 'macd', label: 'MACD' },
  { id: 'breakout', label: 'Breakout' },
  { id: 'simple_trend', label: 'Simple Trend' },
  { id: 'multi_coin', label: 'Multi-Coin Momentum' },
  { id: 'grid', label: 'Grid' },
  { id: 'arbitrage', label: 'Arbitrage' },
  { id: 'ensemble_ml', label: 'ML Ensemble' },
  { id: 'news_sentiment', label: 'News Sentiment' },
];

const inputClass =
  'w-full rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20';

export default function Backtest() {
  const [strategyId, setStrategyId] = useState('momentum');
  const [assetClass, setAssetClass] = useState<'crypto' | 'stock'>('crypto');
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
        strategy_id: strategyId,
        symbol,
        asset_class: assetClass,
        timeframe,
        start_date: '2024-01-01',
        end_date: '2024-04-01',
        initial_balance:
          assetClass === 'crypto'
            ? { USDT: parseFloat(initialBalance) }
            : { USD: parseFloat(initialBalance) },
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
      <div className="space-y-6">
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
            className="panel p-5"
          >
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Backtest Config</h2>
            <form onSubmit={handleRun} className="space-y-3">
              <div>
                <label className="stat-label mb-1.5 block">Strategy</label>
                <select
                  value={strategyId}
                  onChange={(e) => setStrategyId(e.target.value)}
                  className={inputClass}
                >
                  {BACKTESTABLE_STRATEGIES.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="stat-label mb-1.5 block">Asset Class</label>
                <div className="flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
                  <button
                    type="button"
                    onClick={() => {
                      setAssetClass('crypto');
                      setSymbol('BTC-USD');
                    }}
                    className={`flex-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                      assetClass === 'crypto'
                        ? 'bg-bg-elevated text-text-primary shadow-card'
                        : 'text-text-muted hover:text-text-secondary'
                    }`}
                  >
                    Crypto
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAssetClass('stock');
                      setSymbol('AAPL');
                    }}
                    className={`flex-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                      assetClass === 'stock'
                        ? 'bg-bg-elevated text-text-primary shadow-card'
                        : 'text-text-muted hover:text-text-secondary'
                    }`}
                  >
                    Stock
                  </button>
                </div>
              </div>

              <div>
                <label className="stat-label mb-1.5 block">Symbol</label>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  placeholder={assetClass === 'crypto' ? 'BTC-USD' : 'AAPL'}
                  className={`${inputClass} font-mono`}
                />
              </div>

              <div>
                <label className="stat-label mb-1.5 block">Timeframe</label>
                <select
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  className={inputClass}
                >
                  <option value="1h">1 Hour</option>
                  <option value="4h">4 Hour</option>
                  <option value="1d">1 Day</option>
                </select>
              </div>

              <div>
                <label className="stat-label mb-1.5 block">
                  Initial Balance ({assetClass === 'crypto' ? 'USDT' : 'USD'})
                </label>
                <input
                  type="number"
                  value={initialBalance}
                  onChange={(e) => setInitialBalance(e.target.value)}
                  className={`${inputClass} font-mono tabular-nums`}
                />
              </div>

              <button
                type="submit"
                disabled={running}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-cyan py-2.5 text-sm font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90 disabled:opacity-50"
              >
                {running ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
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
                  className="grid grid-cols-2 gap-4 sm:grid-cols-3"
                >
                  <div className="panel p-4">
                    <p className="stat-label">Total Return</p>
                    <p
                      className={`mt-1.5 font-mono text-lg font-semibold tabular-nums ${
                        result.total_return_pct >= 0 ? 'text-success-green' : 'text-danger-red'
                      }`}
                    >
                      {result.total_return_pct >= 0 ? '+' : ''}
                      {result.total_return_pct.toFixed(2)}%
                    </p>
                  </div>
                  <div className="panel p-4">
                    <p className="stat-label">Sharpe Ratio</p>
                    <p className="mt-1.5 font-mono text-lg font-semibold tabular-nums text-text-primary">
                      {result.sharpe_ratio.toFixed(2)}
                    </p>
                  </div>
                  <div className="panel p-4">
                    <p className="stat-label">Max Drawdown</p>
                    <p className="mt-1.5 font-mono text-lg font-semibold tabular-nums text-danger-red">
                      {result.max_drawdown_pct.toFixed(2)}%
                    </p>
                  </div>
                  <div className="panel p-4">
                    <p className="stat-label">Win Rate</p>
                    <p className="mt-1.5 font-mono text-lg font-semibold tabular-nums text-text-primary">
                      {result.win_rate.toFixed(1)}%
                    </p>
                  </div>
                  <div className="panel p-4">
                    <p className="stat-label">Profit Factor</p>
                    <p className="mt-1.5 font-mono text-lg font-semibold tabular-nums text-text-primary">
                      {result.profit_factor.toFixed(2)}
                    </p>
                  </div>
                  <div className="panel p-4">
                    <p className="stat-label">Total Trades</p>
                    <p className="mt-1.5 font-mono text-lg font-semibold tabular-nums text-text-primary">
                      {result.total_trades}
                    </p>
                  </div>
                </motion.div>

                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.1 }}
                  className="panel p-5"
                >
                  <h3 className="mb-3 text-sm font-semibold text-text-primary">Equity Curve</h3>
                  <div className="h-[300px] xl:h-[380px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={result.equity_curve.map((p, i) => ({
                          ...p,
                          day: `Day ${i + 1}`,
                        }))}
                        margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                      >
                        <defs>
                          <linearGradient id="btGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="rgba(34,211,238,0.25)" />
                            <stop offset="100%" stopColor="rgba(34,211,238,0)" />
                          </linearGradient>
                        </defs>
                        <CartesianGrid stroke="#1C2840" strokeDasharray="3 3" vertical={false} />
                        <XAxis
                          dataKey="day"
                          tick={{ fontSize: 11, fill: '#6E7E96' }}
                          axisLine={false}
                          tickLine={false}
                          minTickGap={28}
                        />
                        <YAxis
                          tick={{ fontSize: 11, fill: '#6E7E96' }}
                          axisLine={false}
                          tickLine={false}
                          tickFormatter={(v: number) => `$${v.toFixed(0)}`}
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
                          formatter={(value: number) => [formatCurrency(value), 'Equity']}
                        />
                        <Area type="monotone" dataKey="equity" stroke="#22D3EE" strokeWidth={2} fill="url(#btGradient)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </motion.div>
              </>
            ) : (
              <div className="panel flex h-64 items-center justify-center">
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
