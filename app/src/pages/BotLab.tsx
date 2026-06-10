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
import IdleStateBanner from '@/components/IdleStateBanner';
import {
  getStrategies,
  getTrades,
  registerStrategy,
  toggleStrategy,
  type ApiStrategy,
} from '@/lib/api';

interface PerStrategyMetrics {
  trades: number;
  closed: number;
  wins: number;
  pnl: number;
}

const strategyIcons: Record<string, React.ReactNode> = {
  MomentumStrategy: <TrendingUp className="h-4 w-4" />,
  MeanReversionStrategy: <Activity className="h-4 w-4" />,
  GridStrategy: <Grid3X3 className="h-4 w-4" />,
  BreakoutStrategy: <Zap className="h-4 w-4" />,
  MACDStrategy: <BarChart3 className="h-4 w-4" />,
  ArbitrageStrategy: <Cpu className="h-4 w-4" />,
  EnsembleMLStrategy: <BrainCircuit className="h-4 w-4" />,
  NewsSentimentStrategy: <Activity className="h-4 w-4" />,
};

const MULTI_SYMBOL_STRATEGIES = new Set(['momentum', 'macd', 'mean_reversion']);
const POPULAR_CRYPTO = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE', 'AVAX', 'DOT', 'LINK', 'MATIC', 'LTC'];
const POPULAR_STOCKS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'AMD', 'SPY', 'QQQ', 'NFLX', 'JPM'];

type AssetClass = 'crypto' | 'stock';

export default function BotLab() {
  const [strategies, setStrategies] = useState<ApiStrategy[]>([]);
  const [tradesByStrat, setTradesByStrat] = useState<Record<string, PerStrategyMetrics>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('momentum');
  const [assetClass, setAssetClass] = useState<AssetClass>('crypto');
  const [symbolInput, setSymbolInput] = useState<string>('BTC');
  const [registering, setRegistering] = useState(false);

  const isMultiCapable = MULTI_SYMBOL_STRATEGIES.has(selectedStrategy);
  const POPULAR_SYMBOLS = assetClass === 'stock' ? POPULAR_STOCKS : POPULAR_CRYPTO;

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next);
    // Reset to a sensible default for the new asset class
    setSymbolInput(next === 'stock' ? 'AAPL' : 'BTC');
  };

  useEffect(() => {
    loadBots();
  }, []);

  // /strategies/ returns metrics=null for almost every active bot. Aggregate
  // /trades/ client-side per strategy_id so the per-bot Trades/Win Rate/P&L
  // columns reflect actual fills instead of all-zeroes.
  async function loadBots() {
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
      const tickers = symbolInput
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);
      if (tickers.length === 0) {
        throw new Error('Enter at least one symbol (e.g. BTC or BTC,ETH,SOL)');
      }
      const config: Record<string, unknown> = {
        asset_class: assetClass,
        ...(tickers.length === 1 ? { symbol: tickers[0] } : { symbols: tickers }),
      };
      await registerStrategy(selectedStrategy, config);
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
        <IdleStateBanner />

        {/* Create Bot */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="panel p-5"
        >
          <h2 className="mb-4 text-sm font-semibold text-text-primary">Create New Bot</h2>
          <div className="flex flex-wrap items-end gap-3 xl:gap-4">
            <div>
              <label className="stat-label mb-1.5 block">Asset class</label>
              <div className="inline-flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
                <button
                  type="button"
                  onClick={() => handleAssetClassChange('crypto')}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    assetClass === 'crypto'
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  Crypto
                </button>
                <button
                  type="button"
                  onClick={() => handleAssetClassChange('stock')}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    assetClass === 'stock'
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  Stocks
                </button>
              </div>
            </div>
            <div>
              <label className="stat-label mb-1.5 block">Strategy</label>
              <select
                value={selectedStrategy}
                onChange={(e) => setSelectedStrategy(e.target.value)}
                className="rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              >
                <option value="momentum">Momentum</option>
                <option value="mean_reversion">Mean Reversion</option>
                <option value="grid">Grid</option>
                <option value="breakout">Breakout</option>
                <option value="macd">MACD</option>
                <option value="arbitrage">Arbitrage</option>
                <option value="ensemble_ml">ML Ensemble</option>
                <option value="news_sentiment">News Sentiment</option>
              </select>
            </div>
            <div className="flex flex-col">
              <label className="stat-label mb-1.5 block">
                {isMultiCapable ? 'Symbol(s) — comma-separated' : 'Symbol'}
              </label>
              <input
                type="text"
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                placeholder={isMultiCapable ? 'BTC, ETH, SOL' : 'BTC'}
                className="min-w-[14rem] rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20"
              />
              <div className="mt-1 flex flex-wrap gap-1">
                {POPULAR_SYMBOLS.slice(0, isMultiCapable ? 8 : 6).map((s) => {
                  const currentTickers = symbolInput
                    .split(',')
                    .map((t) => t.trim().toUpperCase())
                    .filter(Boolean);
                  const isSelected = isMultiCapable
                    ? currentTickers.includes(s)
                    : currentTickers.length === 1 && currentTickers[0] === s;
                  return (
                    <button
                      key={s}
                      type="button"
                      onClick={() => {
                        setSymbolInput((prev) => {
                          if (!isMultiCapable) return s;
                          const tickers = prev
                            .split(',')
                            .map((t) => t.trim().toUpperCase())
                            .filter(Boolean);
                          // Use a Set so we never produce duplicates regardless
                          // of how fast clicks land.
                          const set = new Set(tickers);
                          if (set.has(s)) set.delete(s);
                          else set.add(s);
                          return Array.from(set).join(', ');
                        });
                      }}
                      className={`rounded-md border px-1.5 py-0.5 font-mono text-2xs transition-colors ${
                        isSelected
                          ? 'border-accent-cyan bg-accent-cyan/10 text-accent-cyan'
                          : 'border-border-subtle bg-bg-input/50 text-text-secondary hover:border-accent-cyan/50 hover:text-text-primary'
                      }`}
                    >
                      {s}
                    </button>
                  );
                })}
              </div>
            </div>
            <button
              onClick={handleCreateBot}
              disabled={registering}
              className="flex items-center gap-1.5 rounded-lg bg-accent-cyan px-3.5 py-2 text-xs font-semibold text-text-inverse transition-colors hover:bg-accent-cyan/90 disabled:opacity-50"
            >
              {registering ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-text-inverse border-t-transparent" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Create Bot
            </button>
          </div>
          {isMultiCapable && (
            <p className="mt-2 text-xs text-text-muted">
              {selectedStrategy} supports multiple symbols in one bot — it scans each ticker independently and trades whichever signals first.
            </p>
          )}
        </motion.div>

        {/* Active Bots */}
        <div>
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Active Bots</h2>
          {strategies.length === 0 ? (
            <div className="panel p-8 text-center text-sm text-text-muted">
              No active bots. Create one above.
            </div>
          ) : (
            <div className="space-y-3">
              {strategies.map((bot, i) => {
                const metrics = bot.metrics as Record<string, number> | null;
                const agg = tradesByStrat[bot.strategy_id];
                // Merge backend metrics with client-side trade aggregation
                // so cards reflect real fills even when bot.metrics is null.
                const totalTrades = metrics?.total_trades ?? agg?.trades ?? 0;
                const closedTrades = agg?.closed ?? 0;
                const pnlValue = Number(metrics?.total_pnl ?? agg?.pnl ?? 0);
                const winRate =
                  metrics?.win_rate != null
                    ? metrics.win_rate
                    : closedTrades > 0
                    ? (agg!.wins / closedTrades) * 100
                    : null;
                const cfg = bot.config as Record<string, unknown>;
                const symbolsList = Array.isArray(cfg?.symbols) ? (cfg.symbols as string[]) : null;
                // Truncate long lists so a 30-symbol auto_discovery doesn't
                // eat the whole row. Show first 5 inline + "+N more" badge,
                // full list visible on hover via the title attribute.
                const SYM_PREVIEW = 5;
                const fullSymbolList: string[] = symbolsList && symbolsList.length > 0
                  ? symbolsList
                  : (cfg?.symbol ? [String(cfg.symbol)] : []);
                const previewSymbols = fullSymbolList.slice(0, SYM_PREVIEW);
                const overflowCount = Math.max(0, fullSymbolList.length - SYM_PREVIEW);
                const fullLabel = fullSymbolList.length > 0 ? fullSymbolList.join(', ') : '—';
                const assetClassLabel = String(cfg?.asset_class ?? 'crypto').toLowerCase();
                return (
                  <motion.div
                    key={bot.strategy_id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, delay: i * 0.05 }}
                    className="panel panel-hover flex flex-col gap-4 p-5 sm:flex-row sm:items-center"
                  >
                    <div className="flex items-center gap-3">
                      <div className="rounded-lg bg-accent-cyan/10 p-2 text-accent-cyan">
                        {strategyIcons[bot.strategy_type] || <Activity className="h-4 w-4" />}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-text-primary">{bot.strategy_type}</span>
                          <span className={bot.is_active ? 'pill-success' : 'pill-neutral'}>
                            {bot.is_active ? 'Running' : 'Paused'}
                          </span>
                          <span className={assetClassLabel === 'stock' ? 'pill bg-info-purple/10 text-info-purple' : 'pill-info'}>
                            {assetClassLabel === 'stock' ? 'Stock' : 'Crypto'}
                          </span>
                          {fullSymbolList.length === 0 ? (
                            <span
                              className="font-mono text-xs italic text-text-muted"
                              title="No hardcoded symbols — this bot pulls candidates at runtime from the Watchlist / Scanner."
                            >
                              Dynamic universe
                            </span>
                          ) : (
                            <span
                              className="font-mono text-xs text-accent-cyan"
                              title={fullLabel}
                            >
                              {previewSymbols.join(', ')}
                              {overflowCount > 0 && (
                                <span className="ml-1.5 inline-block rounded-md border border-accent-cyan/30 bg-accent-cyan/10 px-1.5 py-0.5 text-2xs text-accent-cyan">
                                  +{overflowCount} more
                                </span>
                              )}
                            </span>
                          )}
                        </div>
                        <p className="text-2xs text-text-muted">{bot.strategy_id}</p>
                      </div>
                    </div>

                    <div className="grid flex-1 grid-cols-3 gap-2 sm:max-w-md sm:justify-self-center">
                      <div className="rounded-lg bg-bg-input p-2.5 text-center">
                        <p className="stat-label">Trades</p>
                        <p className="font-mono text-sm tabular-nums text-text-primary">
                          {totalTrades}
                          {totalTrades > 0 && closedTrades < totalTrades && (
                            <span
                              className="ml-1 text-2xs text-text-muted"
                              title={`${closedTrades} closed, ${totalTrades - closedTrades} open`}
                            >
                              ({closedTrades}c)
                            </span>
                          )}
                        </p>
                      </div>
                      <div className="rounded-lg bg-bg-input p-2.5 text-center">
                        <p className="stat-label">Win Rate</p>
                        <p className="font-mono text-sm tabular-nums text-text-primary">
                          {winRate != null ? `${winRate.toFixed(1)}%` : '—'}
                        </p>
                      </div>
                      <div className="rounded-lg bg-bg-input p-2.5 text-center">
                        <p className="stat-label">P&L</p>
                        <p
                          className={`font-mono text-sm tabular-nums ${
                            pnlValue > 0
                              ? 'text-success-green'
                              : pnlValue < 0
                              ? 'text-danger-red'
                              : 'text-text-primary'
                          }`}
                        >
                          {pnlValue === 0 ? '—' : formatCurrency(pnlValue)}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleToggle(bot.strategy_id, bot.is_active)}
                        aria-label={bot.is_active ? `Pause ${bot.strategy_type} bot` : `Resume ${bot.strategy_type} bot`}
                        title={bot.is_active ? 'Pause bot' : 'Resume bot'}
                        className={`rounded-lg p-2 transition-colors ${
                          bot.is_active
                            ? 'text-warning-amber hover:bg-warning-amber/10'
                            : 'text-success-green hover:bg-success-green/10'
                        }`}
                      >
                        {bot.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button
                        aria-label={`${bot.strategy_type} bot settings`}
                        title="Bot settings"
                        className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-bg-input hover:text-text-primary"
                      >
                        <Settings className="h-4 w-4" />
                      </button>
                      <button
                        aria-label={`Delete ${bot.strategy_type} bot`}
                        title="Delete bot"
                        className="rounded-lg p-2 text-danger-red transition-colors hover:bg-danger-red/10"
                      >
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
