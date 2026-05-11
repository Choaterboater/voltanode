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

  async function loadBots() {
    try {
      setLoading(true);
      const res = await getStrategies();
      setStrategies(res.strategies);
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

        {/* Create Bot */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h2 className="mb-3 text-base font-semibold text-text-primary">Create New Bot</h2>
          <div className="flex flex-wrap items-end gap-3 xl:gap-4">
            <div>
              <label className="mb-1 block text-xs text-text-muted">Asset class</label>
              <div className="inline-flex rounded-md border border-border-subtle bg-bg-input p-0.5">
                <button
                  type="button"
                  onClick={() => handleAssetClassChange('crypto')}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    assetClass === 'crypto'
                      ? 'bg-accent-cyan text-text-inverse'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  Crypto
                </button>
                <button
                  type="button"
                  onClick={() => handleAssetClassChange('stock')}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    assetClass === 'stock'
                      ? 'bg-accent-cyan text-text-inverse'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  Stocks
                </button>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-muted">Strategy</label>
              <select
                value={selectedStrategy}
                onChange={(e) => setSelectedStrategy(e.target.value)}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
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
              <label className="mb-1 block text-xs text-text-muted">
                {isMultiCapable ? 'Symbol(s) — comma-separated' : 'Symbol'}
              </label>
              <input
                type="text"
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                placeholder={isMultiCapable ? 'BTC, ETH, SOL' : 'BTC'}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan min-w-[14rem]"
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
                      className={`rounded border px-1.5 py-0.5 text-[10px] font-mono transition-colors ${
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
          {isMultiCapable && (
            <p className="mt-2 text-xs text-text-muted">
              {selectedStrategy} supports multiple symbols in one bot — it scans each ticker independently and trades whichever signals first.
            </p>
          )}
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
                          <Badge variant={assetClassLabel === 'stock' ? 'info' : 'cyan'}>
                            {assetClassLabel === 'stock' ? 'Stock' : 'Crypto'}
                          </Badge>
                          {fullSymbolList.length === 0 ? (
                            <span
                              className="font-mono text-xs text-text-muted italic"
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
                                <span className="ml-1.5 inline-block rounded border border-accent-cyan/30 bg-accent-cyan/10 px-1.5 py-0.5 text-[10px] text-accent-cyan">
                                  +{overflowCount} more
                                </span>
                              )}
                            </span>
                          )}
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
                        aria-label={bot.is_active ? `Pause ${bot.strategy_type} bot` : `Resume ${bot.strategy_type} bot`}
                        title={bot.is_active ? 'Pause bot' : 'Resume bot'}
                        className={`rounded-md p-2 transition-colors ${
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
                        className="rounded-md p-2 text-text-secondary hover:bg-bg-input hover:text-text-primary transition-colors"
                      >
                        <Settings className="h-4 w-4" />
                      </button>
                      <button
                        aria-label={`Delete ${bot.strategy_type} bot`}
                        title="Delete bot"
                        className="rounded-md p-2 text-danger-red hover:bg-danger-red/10 transition-colors"
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
