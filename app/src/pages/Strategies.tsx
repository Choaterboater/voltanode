import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Play,
  Pause,
  Settings,
  TrendingUp,
  BarChart3,
  Grid3X3,
  Zap,
  Cpu,
  BrainCircuit,
  Activity,
} from 'lucide-react';
import Layout from '@/components/Layout';
import { getStrategies, getTrades, registerStrategy, toggleStrategy, type ApiStrategy } from '@/lib/api';

interface PerStrategyMetrics {
  trades: number;
  closed: number;
  wins: number;
  pnl: number;
}

// Backend returns strategy_type in snake_case (e.g. "mean_reversion"),
// so these lookup tables must use snake_case keys — previously they were
// PascalCase and never matched, leaving every card with the fallback
// "Custom strategy" copy and the generic Activity icon.
const strategyIcons: Record<string, React.ReactNode> = {
  momentum: <TrendingUp className="h-5 w-5" />,
  mean_reversion: <Activity className="h-5 w-5" />,
  grid: <Grid3X3 className="h-5 w-5" />,
  breakout: <Zap className="h-5 w-5" />,
  macd: <BarChart3 className="h-5 w-5" />,
  arbitrage: <Cpu className="h-5 w-5" />,
  ensemble_ml: <BrainCircuit className="h-5 w-5" />,
  news_sentiment: <BrainCircuit className="h-5 w-5" />,
  auto_discovery: <Zap className="h-5 w-5" />,
  squeeze: <TrendingUp className="h-5 w-5" />,
  simple_trend: <TrendingUp className="h-5 w-5" />,
  multi_coin: <Cpu className="h-5 w-5" />,
};

const strategyDescriptions: Record<string, string> = {
  momentum: 'Trend-following using EMA crossovers. Best in directional markets.',
  mean_reversion: 'RSI + Bollinger Bands. Buys oversold, sells overbought.',
  grid: 'Systematic grid orders. Profits from ranging markets.',
  breakout: 'Support/resistance breakouts with volume confirmation.',
  macd: 'Signal line crossovers with histogram divergence.',
  arbitrage: 'Cross-market price discrepancy scanner.',
  ensemble_ml: 'Multi-indicator weighted scoring ensemble.',
  news_sentiment: 'Sentiment-driven trades from headlines + LLM scoring.',
  auto_discovery: 'Scans the universe and trades top composite-scored candidates.',
  squeeze: '7-factor short-squeeze pattern trader. Wider stops, longer holds.',
  simple_trend: 'Lightweight EMA-50/200 trend filter. Conservative entries.',
  multi_coin: 'Momentum scanner across multiple crypto pairs simultaneously.',
};

export default function Strategies() {
  const [strategies, setStrategies] = useState<ApiStrategy[]>([]);
  const [tradesByStrat, setTradesByStrat] = useState<Record<string, PerStrategyMetrics>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState<string | null>(null);

  useEffect(() => {
    loadAll();
  }, []);

  // The /strategies/ endpoint returns metrics=null for almost every bot
  // (the engine doesn't populate ApiStrategy.metrics until a closed-PnL
  // round-trip lands), so every card showed Trades=0 even when the bot
  // had fired BUYs. Aggregate /trades/ client-side per strategy_id and
  // merge in.
  async function loadAll() {
    try {
      setLoading(true);
      const [stratsRes, trades] = await Promise.all([getStrategies(), getTrades()]);
      setStrategies(stratsRes.strategies);
      const agg: Record<string, PerStrategyMetrics> = {};
      for (const t of trades) {
        const sid = t.strategy_id ?? '';
        if (!sid) continue;
        if (!agg[sid]) agg[sid] = { trades: 0, closed: 0, wins: 0, pnl: 0 };
        agg[sid].trades += 1;
        if (t.realized_pnl != null) {
          agg[sid].closed += 1;
          agg[sid].pnl += t.realized_pnl;
          if (t.realized_pnl > 0) agg[sid].wins += 1;
        }
      }
      setTradesByStrat(agg);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
  }

  async function loadStrategies() {
    await loadAll();
  }

  async function handleToggle(s: ApiStrategy) {
    try {
      await toggleStrategy(s.strategy_id, !s.is_active);
      await loadStrategies();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Toggle failed');
    }
  }

  async function handleRegister(strategyType: string) {
    try {
      setRegistering(strategyType);
      await registerStrategy(strategyType);
      await loadStrategies();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Registration failed');
    } finally {
      setRegistering(null);
    }
  }

  // Registered = bots the user (or auto-deploy) has created — they have a
  // timestamp suffix on their ID like `momentum_1777844811849`.
  // Available = the bare "strategy_type" templates the backend exposes
  // via /strategies/available (no underscore-timestamp), which a user
  // can clone via Register & Activate. Previously both filters matched
  // strategies with `metrics: null`, which caused every active bot to
  // also appear in the Strategy Library below — same card twice.
  const TEMPLATE_IDS = new Set([
    'momentum', 'mean_reversion', 'grid', 'breakout', 'macd', 'arbitrage',
    'ensemble_ml', 'news_sentiment', 'multi_coin', 'simple_trend',
    'auto_discovery', 'squeeze',
  ]);
  const registered = strategies.filter((s) => !TEMPLATE_IDS.has(s.strategy_id));
  const available = strategies.filter((s) => TEMPLATE_IDS.has(s.strategy_id));

  if (loading) {
    return (
      <Layout title="Strategies">
        <div className="flex h-64 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-cyan border-t-transparent" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Strategies">
      <div className="space-y-6">
        {error && (
          <div className="rounded-lg border border-danger-red/30 bg-danger-red/10 px-4 py-2 text-sm text-danger-red">
            {error}
          </div>
        )}

        {/* Registered / Active */}
        <div>
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Active Strategies</h2>
          {registered.length === 0 ? (
            <div className="panel p-8 text-center text-sm text-text-muted">
              No strategies registered yet. Register one below.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {registered.map((s, i) => {
                const m = (s.metrics as Record<string, number> | null) || null;
                const cfg = (s.config as Record<string, unknown>) || {};
                const symList: string[] = Array.isArray(cfg.symbols)
                  ? (cfg.symbols as string[])
                  : cfg.symbol
                  ? [String(cfg.symbol)]
                  : [];
                // Prefer backend metrics if present; otherwise fall back to
                // the client-side aggregation of /trades by strategy_id.
                const agg = tradesByStrat[s.strategy_id];
                const totalTrades = m?.total_trades ?? agg?.trades ?? 0;
                const closedTrades = agg?.closed ?? 0;
                const pnl = Number(m?.total_pnl ?? agg?.pnl ?? 0);
                const winRate =
                  m?.win_rate != null
                    ? m.win_rate
                    : closedTrades > 0
                    ? ((agg!.wins / closedTrades) * 100)
                    : undefined;
                return (
                <motion.div
                  key={s.strategy_id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: i * 0.04 }}
                  className="panel panel-hover flex h-full flex-col p-5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="rounded-lg bg-accent-cyan/10 p-2 text-accent-cyan">
                        {strategyIcons[s.strategy_type] || <Activity className="h-5 w-5" />}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-text-primary">{s.strategy_type}</p>
                        <p
                          className="truncate font-mono text-2xs text-text-muted"
                          title={s.strategy_id}
                        >
                          {s.strategy_id}
                        </p>
                      </div>
                    </div>
                    <span className={s.is_active ? 'pill-success' : 'pill-neutral'}>
                      {s.is_active ? 'Active' : 'Idle'}
                    </span>
                  </div>

                  <p className="mt-3 text-xs text-text-secondary">
                    {strategyDescriptions[s.strategy_type] || 'Custom strategy.'}
                  </p>

                  {/* Symbol chips */}
                  <div className="mt-3 flex flex-wrap gap-1">
                    {symList.length === 0 ? (
                      <span className="text-2xs italic text-text-muted">
                        Dynamic universe
                      </span>
                    ) : (
                      <>
                        {symList.slice(0, 4).map((sym) => (
                          <span
                            key={sym}
                            className="pill-neutral font-mono normal-case"
                          >
                            {sym}
                          </span>
                        ))}
                        {symList.length > 4 && (
                          <span
                            className="pill-neutral font-mono normal-case"
                            title={symList.join(', ')}
                          >
                            +{symList.length - 4}
                          </span>
                        )}
                      </>
                    )}
                  </div>

                  {/* Always-on metrics block so cards have consistent height */}
                  <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border-subtle/60 pt-3">
                    <div>
                      <p className="stat-label">Win Rate</p>
                      <p className="font-mono text-sm tabular-nums text-text-primary">
                        {winRate != null ? `${winRate.toFixed(1)}%` : '—'}
                      </p>
                    </div>
                    <div>
                      <p className="stat-label">Trades</p>
                      <p className="font-mono text-sm tabular-nums text-text-primary">{totalTrades}</p>
                    </div>
                    <div>
                      <p className="stat-label">P&L</p>
                      <p
                        className={`font-mono text-sm tabular-nums ${
                          pnl > 0
                            ? 'text-success-green'
                            : pnl < 0
                            ? 'text-danger-red'
                            : 'text-text-primary'
                        }`}
                      >
                        {pnl === 0 ? '—' : `${pnl > 0 ? '+' : ''}${pnl.toFixed(2)}`}
                      </p>
                    </div>
                  </div>

                  <div className="mt-auto flex items-center gap-2 pt-4">
                    <button
                      onClick={() => handleToggle(s)}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-xs font-medium transition-colors ${
                        s.is_active
                          ? 'border-border-subtle bg-bg-elevated/60 text-text-secondary hover:border-accent-cyan/30 hover:text-text-primary'
                          : 'border-success-green/30 bg-success-green/10 text-success-green hover:bg-success-green/20'
                      }`}
                    >
                      {s.is_active ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      {s.is_active ? 'Pause' : 'Activate'}
                    </button>
                    <button className="rounded-lg p-2 text-text-muted hover:bg-bg-elevated hover:text-text-primary transition-colors">
                      <Settings className="h-4 w-4" />
                    </button>
                  </div>
                </motion.div>
                );
              })}
            </div>
          )}
        </div>

        {/* Available Library */}
        <div>
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Strategy Library</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {available.map((s, i) => (
              <motion.div
                key={s.strategy_id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.08 }}
                className="panel panel-hover p-5 opacity-80 hover:opacity-100 transition-opacity"
              >
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-bg-elevated p-2 text-text-secondary">
                    {strategyIcons[s.strategy_type] || <Activity className="h-5 w-5" />}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-text-primary">{s.strategy_type}</p>
                    <p className="text-xs text-text-muted">{strategyDescriptions[s.strategy_type] || 'Custom strategy'}</p>
                  </div>
                </div>

                <div className="mt-3 space-y-1">
                  {Object.entries(s.config).slice(0, 4).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-xs">
                      <span className="text-text-muted">{k}</span>
                      <span className="font-mono tabular-nums text-text-secondary">{String(v)}</span>
                    </div>
                  ))}
                </div>

                <button
                  onClick={() => handleRegister(s.strategy_type)}
                  disabled={registering === s.strategy_type}
                  className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent-cyan px-3.5 py-2 text-xs font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90 disabled:opacity-50"
                >
                  {registering === s.strategy_type ? (
                    <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  Register & Activate
                </button>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </Layout>
  );
}
