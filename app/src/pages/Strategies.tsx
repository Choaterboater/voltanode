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
import Badge from '@/components/Badge';
import { getStrategies, registerStrategy, toggleStrategy, type ApiStrategy } from '@/lib/api';

const strategyIcons: Record<string, React.ReactNode> = {
  Momentum: <TrendingUp className="h-5 w-5" />,
  MeanReversion: <Activity className="h-5 w-5" />,
  Grid: <Grid3X3 className="h-5 w-5" />,
  Breakout: <Zap className="h-5 w-5" />,
  MACD: <BarChart3 className="h-5 w-5" />,
  Arbitrage: <Cpu className="h-5 w-5" />,
  EnsembleML: <BrainCircuit className="h-5 w-5" />,
};

const strategyDescriptions: Record<string, string> = {
  Momentum: 'Trend-following using EMA crossovers. Best in directional markets.',
  MeanReversion: 'RSI + Bollinger Bands. Profits from price reversions to mean.',
  Grid: 'Systematic grid orders. Profits from ranging markets.',
  Breakout: 'Support/resistance breakouts with volume confirmation.',
  MACD: 'Signal line crossovers with histogram divergence.',
  Arbitrage: 'Cross-market price discrepancy scanner.',
  EnsembleML: 'Multi-indicator weighted scoring ensemble.',
};

export default function Strategies() {
  const [strategies, setStrategies] = useState<ApiStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState<string | null>(null);

  useEffect(() => {
    loadStrategies();
  }, []);

  async function loadStrategies() {
    try {
      setLoading(true);
      const res = await getStrategies();
      setStrategies(res.strategies);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
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

  const available = strategies.filter((s) => !s.metrics);
  const registered = strategies.filter((s) => s.metrics !== undefined || s.is_active);

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
          <h2 className="mb-3 text-lg font-semibold text-text-primary">Active Strategies</h2>
          {registered.length === 0 ? (
            <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-8 text-center text-sm text-text-muted">
              No strategies registered yet. Register one below.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {registered.map((s, i) => (
                <motion.div
                  key={s.strategy_id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: i * 0.08 }}
                  className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="rounded-lg bg-accent-cyan/10 p-2 text-accent-cyan">
                        {strategyIcons[s.strategy_type] || <Activity className="h-5 w-5" />}
                      </div>
                      <div>
                        <p className="font-medium text-text-primary">{s.strategy_type}</p>
                        <p className="text-xs text-text-muted">{s.strategy_id}</p>
                      </div>
                    </div>
                    <Badge variant={s.is_active ? 'success' : 'neutral'}>
                      {s.is_active ? 'Active' : 'Idle'}
                    </Badge>
                  </div>

                  <p className="mt-3 text-sm text-text-secondary">
                    {strategyDescriptions[s.strategy_type] || 'Custom strategy'}
                  </p>

                  {s.metrics && (
                    <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                      <div className="rounded bg-bg-input p-2">
                        <p className="text-text-muted">Win Rate</p>
                        <p className="font-mono text-text-primary">
                          {((s.metrics as Record<string, unknown>).win_rate as number)?.toFixed(1) ?? '-'}%
                        </p>
                      </div>
                      <div className="rounded bg-bg-input p-2">
                        <p className="text-text-muted">Trades</p>
                        <p className="font-mono text-text-primary">
                          {((s.metrics as Record<string, unknown>).total_trades as number) ?? '-'}
                        </p>
                      </div>
                      <div className="rounded bg-bg-input p-2">
                        <p className="text-text-muted">P&L</p>
                        <p className="font-mono text-text-primary">
                          {((s.metrics as Record<string, unknown>).total_pnl as number)?.toFixed(2) ?? '-'}
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="mt-4 flex items-center gap-2">
                    <button
                      onClick={() => handleToggle(s)}
                      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                        s.is_active
                          ? 'bg-warning-amber/10 text-warning-amber hover:bg-warning-amber/20'
                          : 'bg-success-green/10 text-success-green hover:bg-success-green/20'
                      }`}
                    >
                      {s.is_active ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      {s.is_active ? 'Pause' : 'Activate'}
                    </button>
                    <button className="rounded-md p-1.5 text-text-secondary hover:bg-bg-input hover:text-text-primary transition-colors">
                      <Settings className="h-4 w-4" />
                    </button>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        {/* Available Library */}
        <div>
          <h2 className="mb-3 text-lg font-semibold text-text-primary">Strategy Library</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {available.map((s, i) => (
              <motion.div
                key={s.strategy_id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.08 }}
                className="rounded-[10px] border border-border-subtle bg-bg-surface p-5 opacity-80 hover:opacity-100 transition-opacity"
              >
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-bg-elevated p-2 text-text-secondary">
                    {strategyIcons[s.strategy_type] || <Activity className="h-5 w-5" />}
                  </div>
                  <div>
                    <p className="font-medium text-text-primary">{s.strategy_type}</p>
                    <p className="text-xs text-text-muted">{strategyDescriptions[s.strategy_type] || 'Custom strategy'}</p>
                  </div>
                </div>

                <div className="mt-3 space-y-1">
                  {Object.entries(s.config).slice(0, 4).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-xs">
                      <span className="text-text-muted">{k}</span>
                      <span className="font-mono text-text-secondary">{String(v)}</span>
                    </div>
                  ))}
                </div>

                <button
                  onClick={() => handleRegister(s.strategy_type)}
                  disabled={registering === s.strategy_type}
                  className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
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
