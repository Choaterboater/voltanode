import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Play,
  Pause,
  Settings,
  Trash2,
  Plus,
  TrendingUp,
  Activity,
  Grid3X3,
  Zap,
  BarChart3,
  Cpu,
  BrainCircuit,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';
import {
  getStrategies,
  registerStrategy,
  toggleStrategy,
  type ApiStrategy,
} from '@/lib/api';

const strategyIcons: Record<string, React.ReactNode> = {
  Momentum: <TrendingUp className="h-4 w-4" />,
  MeanReversion: <Activity className="h-4 w-4" />,
  Grid: <Grid3X3 className="h-4 w-4" />,
  Breakout: <Zap className="h-4 w-4" />,
  MACD: <BarChart3 className="h-4 w-4" />,
  Arbitrage: <Cpu className="h-4 w-4" />,
  EnsembleML: <BrainCircuit className="h-4 w-4" />,
};

export default function BotLab() {
  const [strategies, setStrategies] = useState<ApiStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('Momentum');
  const [registering, setRegistering] = useState(false);

  useEffect(() => {
    loadBots();
  }, []);

  async function loadBots() {
    try {
      setLoading(true);
      const res = await getStrategies();
      setStrategies(res.strategies.filter((s) => s.is_active || s.metrics));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load bots');
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(id: string, current: boolean) {
    try {
      await toggleStrategy(id, !current);
      await loadBots();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Toggle failed');
    }
  }

  async function handleCreateBot() {
    try {
      setRegistering(true);
      await registerStrategy(selectedStrategy);
      await loadBots();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create bot');
    } finally {
      setRegistering(false);
    }
  }

  const formatCurrency = (v: number) =>
    `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  if (loading) {
    return (
      <Layout title="Bot Lab">
        <div className="flex h-64 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-cyan border-t-transparent" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Bot Lab">
      <div className="space-y-5">
        {error && (
          <div className="rounded-lg border border-danger-red/30 bg-danger-red/10 px-4 py-2 text-sm text-danger-red">
            {error}
          </div>
        )}

        {/* Create Bot */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h2 className="mb-3 text-base font-semibold text-text-primary">Create New Bot</h2>
          <div className="flex flex-wrap items-end gap-3 xl:gap-4">
            <div>
              <label className="mb-1 block text-xs text-text-muted">Strategy</label>
              <select
                value={selectedStrategy}
                onChange={(e) => setSelectedStrategy(e.target.value)}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
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
            <button
              onClick={handleCreateBot}
              disabled={registering}
              className="flex items-center gap-1.5 rounded-md bg-accent-cyan px-4 py-2 text-sm font-semibold text-text-inverse hover:brightness-110 transition-all disabled:opacity-50"
            >
              {registering ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Create Bot
            </button>
          </div>
        </motion.div>

        {/* Active Bots */}
        <div>
          <h2 className="mb-3 text-lg font-semibold text-text-primary">Active Bots</h2>
          {strategies.length === 0 ? (
            <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-8 text-center text-sm text-text-muted">
              No active bots. Create one above.
            </div>
          ) : (
            <div className="space-y-3">
              {strategies.map((bot, i) => {
                const metrics = bot.metrics as Record<string, number> | null;
                return (
                  <motion.div
                    key={bot.strategy_id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, delay: i * 0.05 }}
                    className="flex flex-col gap-3 rounded-[10px] border border-border-subtle bg-bg-surface p-4 sm:flex-row sm:items-center"
                  >
                    <div className="flex items-center gap-3">
                      <div className="rounded-lg bg-accent-cyan/10 p-2 text-accent-cyan">
                        {strategyIcons[bot.strategy_type] || <Activity className="h-4 w-4" />}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-text-primary">{bot.strategy_type}</span>
                          <Badge variant={bot.is_active ? 'success' : 'neutral'}>
                            {bot.is_active ? 'Running' : 'Paused'}
                          </Badge>
                        </div>
                        <p className="text-xs text-text-muted">{bot.strategy_id}</p>
                      </div>
                    </div>

                    <div className="flex flex-1 flex-wrap gap-4 sm:justify-center">
                      <div className="text-center">
                        <p className="text-xs text-text-muted">Trades</p>
                        <p className="font-mono text-sm text-text-primary">
                          {metrics?.total_trades ?? 0}
                        </p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-text-muted">Win Rate</p>
                        <p className="font-mono text-sm text-text-primary">
                          {metrics?.win_rate ? `${metrics.win_rate.toFixed(1)}%` : '-'}
                        </p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-text-muted">P&L</p>
                        <p
                          className={`font-mono text-sm ${
                            (metrics?.total_pnl ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'
                          }`}
                        >
                          {metrics?.total_pnl ? formatCurrency(metrics.total_pnl) : '-'}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleToggle(bot.strategy_id, bot.is_active)}
                        className={`rounded-md p-2 transition-colors ${
                          bot.is_active
                            ? 'text-warning-amber hover:bg-warning-amber/10'
                            : 'text-success-green hover:bg-success-green/10'
                        }`}
                      >
                        {bot.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button className="rounded-md p-2 text-text-secondary hover:bg-bg-input hover:text-text-primary transition-colors">
                        <Settings className="h-4 w-4" />
                      </button>
                      <button className="rounded-md p-2 text-danger-red hover:bg-danger-red/10 transition-colors">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
