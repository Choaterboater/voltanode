import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  Zap,
  ChevronRight,
  X,
  BookOpen,
  SlidersHorizontal,
  LineChart,
  AlertTriangle,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';
import { strategies } from '@/data/mockData';
import type { Strategy, StrategyParam } from '@/types';

// ── Strategy Detail Data ──
const strategyDetails: Record<string, {
  howItWorks: string;
  bestConditions: string;
  riskLevel: string;
  entryRules: string[];
  exitRules: string[];
}> = {
  'strat-1': {
    howItWorks: 'This strategy follows the trend using EMA crossovers. When the fast EMA (12) crosses above the slow EMA (26) and price is above the long-term trend filter (200 EMA), a BUY signal is generated. When the fast EMA crosses below the slow EMA, a SELL signal triggers. Confidence scales with momentum strength relative to ATR.',
    bestConditions: 'Trending markets with clear directional momentum. Works best when assets are in sustained uptrends or downtrends. Poor performance in choppy, sideways markets.',
    riskLevel: 'Medium-High',
    entryRules: ['Fast EMA crosses above Slow EMA', 'Price above 200 EMA (trend confirmation)', 'Momentum strength > ATR threshold'],
    exitRules: ['Fast EMA crosses below Slow EMA', 'Stop loss hit at configured %', 'Trend filter invalidated'],
  },
  'strat-2': {
    howItWorks: 'A counter-trend strategy that buys when price is statistically "too cheap" and sells when "too expensive." Uses RSI to detect oversold (<30) and overbought (>70) conditions combined with Bollinger Band touches for confirmation. The more extreme the RSI reading, the stronger the signal.',
    bestConditions: 'Range-bound / sideways markets where prices oscillate around a mean. Best when assets regularly revert to average after short-term spikes or drops.',
    riskLevel: 'Medium',
    entryRules: ['RSI below oversold threshold (30)', 'Price touches lower Bollinger Band', 'Price deviates >2 std dev from mean'],
    exitRules: ['RSI returns to neutral (50)', 'Price reaches middle Bollinger Band', 'Price breaks upper band (opposite signal)'],
  },
  'strat-3': {
    howItWorks: 'Sets up a grid of buy and sell orders at fixed price intervals around a center price. As price moves up through a grid level, it sells. As price moves down, it buys. Each filled grid level generates a small profit equal to the grid spacing. No directional prediction needed.',
    bestConditions: 'Ranging markets with consistent volatility. Ideal when an asset trades in a well-defined range without strong directional breaks. Requires sufficient capital to maintain all grid levels.',
    riskLevel: 'Low-Medium',
    entryRules: ['Price crosses below a grid buy level', 'Grid level has available capital', 'Price within configured grid bounds'],
    exitRules: ['Price crosses above a grid sell level', 'Upper/lower grid boundary breached', 'Manual stop or capital exhausted'],
  },
  'strat-4': {
    howItWorks: 'Identifies consolidation periods by tracking support (lookback low) and resistance (lookback high). When price breaks above resistance by a threshold percentage with volume confirmation, it enters long. When price breaks below support with volume, it enters short. Captures the start of explosive moves.',
    bestConditions: 'Markets transitioning from consolidation to trending. Best after prolonged sideways action where volatility has compressed and is ready to expand.',
    riskLevel: 'High',
    entryRules: ['Price breaks above resistance + threshold %', 'Volume > average × multiplier', 'Consolidation period confirmed'],
    exitRules: ['Price returns to breakout level (false break)', 'Opposite direction breakout', 'Trailing stop hit'],
  },
  'strat-5': {
    howItWorks: 'Computes the MACD line (fast EMA minus slow EMA) and signal line (EMA of MACD). A BUY generates when MACD crosses above signal with positive histogram. A SELL generates on bearish cross with negative histogram. Histogram divergence provides early warning signals.',
    bestConditions: 'Trending markets with moderate volatility. Works well in directional moves where momentum builds gradually rather than exploding.',
    riskLevel: 'Medium',
    entryRules: ['MACD line crosses above Signal line', 'Histogram turns positive', 'No bearish divergence on price'],
    exitRules: ['MACD crosses below Signal line', 'Histogram turns negative', 'Divergence between price and MACD'],
  },
  'strat-6': {
    howItWorks: 'Monitors the same asset across multiple exchanges (or market data sources). When the price spread between the cheapest and most expensive market exceeds the minimum threshold after accounting for fees, it generates a BUY signal on the cheap market with metadata to sell on the expensive one.',
    bestConditions: 'High-liquidity assets on multiple exchanges where temporary price discrepancies occur. Requires fast execution infrastructure to capture spreads before they close.',
    riskLevel: 'Very Low',
    entryRules: ['Price spread > min_spread_pct', 'Spread remains profitable after fees', 'Both markets have sufficient liquidity'],
    exitRules: ['Spread closes below fee-adjusted breakeven', 'Execution timeout', 'Either side liquidity dried up'],
  },
  'strat-7': {
    howItWorks: 'Combines 5 technical indicators into a weighted composite score: RSI (0.2), MACD (0.3), EMA Cross (0.2), Bollinger Position (0.15), Volume Trend (0.15). Each is normalized to [-1, 1]. BUY when score > 0.6, SELL when < -0.6. Optional Random Forest classifier blends in after 100 samples if sklearn is available.',
    bestConditions: 'Versatile across all market conditions due to multi-factor analysis. Particularly strong in transitional markets where single-indicator strategies would generate false signals.',
    riskLevel: 'Medium',
    entryRules: ['Composite score > buy threshold (0.6)', 'Minimum 3 of 5 indicators aligned', 'Volume confirms direction'],
    exitRules: ['Composite score < sell threshold (-0.6)', 'Model confidence drops below minimum', 'Retraining cycle triggered'],
  },
};

// ── Helpers ──
function categoryColor(cat: string): string {
  const map: Record<string, string> = {
    Trend: 'bg-success-green/10 text-success-green border-success-green/20',
    'Counter-Trend': 'bg-warning-amber/10 text-warning-amber border-warning-amber/20',
    Systematic: 'bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20',
    Volatility: 'bg-danger-red/10 text-danger-red border-danger-red/20',
    Indicator: 'bg-info-purple/10 text-info-purple border-info-purple/20',
    'AI/ML': 'bg-accent-electric/10 text-accent-electric border-accent-electric/20',
  };
  return map[cat] || 'bg-bg-elevated text-text-secondary border-border-subtle';
}

function riskBadgeVariant(risk: string): 'success' | 'warning' | 'danger' | 'info' {
  if (risk.includes('Low')) return 'success';
  if (risk.includes('Medium')) return 'warning';
  if (risk.includes('High')) return 'danger';
  return 'info';
}

function renderParamValue(param: StrategyParam) {
  if (param.type === 'boolean') return param.default ? 'Yes' : 'No';
  return String(param.default);
}

// ── Strategy Card ──
function StrategyCard({ strategy, onClick }: { strategy: Strategy; onClick: () => void }) {
  const detail = strategyDetails[strategy.id];
  return (
    <motion.div
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="cursor-pointer rounded-[10px] border border-border-subtle bg-bg-surface p-4 transition-colors hover:border-accent-cyan/30"
    >
      <div className="flex items-start justify-between">
        <div>
          <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${categoryColor(strategy.category)}`}>
            {strategy.category}
          </span>
          <h3 className="mt-2 text-base font-semibold text-text-primary">{strategy.name}</h3>
        </div>
        <ChevronRight className="h-4 w-4 text-text-muted" />
      </div>

      <p className="mt-2 text-xs leading-relaxed text-text-muted line-clamp-2">{strategy.description}</p>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <div className="rounded-md bg-bg-input p-2 text-center">
          <p className="text-[10px] text-text-muted">Win Rate</p>
          <p className="mt-0.5 font-mono text-sm text-success-green">{strategy.winRate}%</p>
        </div>
        <div className="rounded-md bg-bg-input p-2 text-center">
          <p className="text-[10px] text-text-muted">Avg Return</p>
          <p className="mt-0.5 font-mono text-sm text-text-primary">{strategy.avgReturn}%</p>
        </div>
        <div className="rounded-md bg-bg-input p-2 text-center">
          <p className="text-[10px] text-text-muted">Sharpe</p>
          <p className="mt-0.5 font-mono text-sm text-text-primary">{strategy.sharpeRatio}</p>
        </div>
      </div>

      {detail && (
        <div className="mt-2 flex items-center gap-1.5">
          <Badge variant={riskBadgeVariant(detail.riskLevel)}>
            {detail.riskLevel} Risk
          </Badge>
          <span className="text-[10px] text-text-muted">{strategy.tradesCount} trades</span>
        </div>
      )}
    </motion.div>
  );
}

// ── Strategy Detail Modal ──
function StrategyDetail({ strategy, onClose }: { strategy: Strategy; onClose: () => void }) {
  const detail = strategyDetails[strategy.id];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-6"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        transition={{ duration: 0.2 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-[12px] border border-border-subtle bg-bg-surface shadow-2xl"
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-subtle bg-bg-surface/95 backdrop-blur px-5 py-4">
          <div className="flex items-center gap-3">
            <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${categoryColor(strategy.category)}`}>
              {strategy.category}
            </span>
            <h2 className="text-lg font-bold text-text-primary">{strategy.name}</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-text-muted hover:bg-bg-input hover:text-text-primary transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 p-5">
          {/* Description */}
          <p className="text-sm leading-relaxed text-text-secondary">{strategy.description}</p>

          {/* Performance Metrics */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg bg-bg-input p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-text-muted">Win Rate</p>
              <p className="mt-1 font-mono text-lg font-semibold text-success-green">{strategy.winRate}%</p>
            </div>
            <div className="rounded-lg bg-bg-input p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-text-muted">Avg Return</p>
              <p className="mt-1 font-mono text-lg font-semibold text-text-primary">{strategy.avgReturn}%</p>
            </div>
            <div className="rounded-lg bg-bg-input p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-text-muted">Sharpe Ratio</p>
              <p className="mt-1 font-mono text-lg font-semibold text-text-primary">{strategy.sharpeRatio}</p>
            </div>
            <div className="rounded-lg bg-bg-input p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-text-muted">Max Drawdown</p>
              <p className="mt-1 font-mono text-lg font-semibold text-danger-red">{strategy.maxDrawdown}%</p>
            </div>
          </div>

          {detail && (
            <>
              {/* How It Works */}
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <BookOpen className="h-4 w-4 text-accent-cyan" />
                  <h3 className="text-sm font-semibold text-text-primary">How It Works</h3>
                </div>
                <div className="rounded-lg border border-border-subtle bg-bg-base p-3">
                  <p className="text-xs leading-relaxed text-text-secondary">{detail.howItWorks}</p>
                </div>
              </div>

              {/* Entry & Exit Rules */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-success-green" />
                    <h3 className="text-sm font-semibold text-text-primary">Entry Rules</h3>
                  </div>
                  <ul className="space-y-1.5">
                    {detail.entryRules.map((rule, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-success-green" />
                        {rule}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 rotate-180 text-danger-red" />
                    <h3 className="text-sm font-semibold text-text-primary">Exit Rules</h3>
                  </div>
                  <ul className="space-y-1.5">
                    {detail.exitRules.map((rule, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-danger-red" />
                        {rule}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              {/* Best Conditions & Risk */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-border-subtle bg-bg-base p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <LineChart className="h-4 w-4 text-accent-cyan" />
                    <h3 className="text-sm font-semibold text-text-primary">Best Market Conditions</h3>
                  </div>
                  <p className="text-xs leading-relaxed text-text-secondary">{detail.bestConditions}</p>
                </div>
                <div className="rounded-lg border border-border-subtle bg-bg-base p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-warning-amber" />
                    <h3 className="text-sm font-semibold text-text-primary">Risk Level</h3>
                  </div>
                  <Badge variant={riskBadgeVariant(detail.riskLevel)}>{detail.riskLevel}</Badge>
                  <p className="mt-2 text-xs leading-relaxed text-text-secondary">
                    {detail.riskLevel.includes('High')
                      ? 'This strategy can experience significant drawdowns. Use smaller position sizes and strict stop losses.'
                      : detail.riskLevel.includes('Low')
                      ? 'Relatively conservative with controlled downside. Suitable for steady capital preservation.'
                      : 'Balanced risk-reward profile. Appropriate for most portfolios with standard risk management.'}
                  </p>
                </div>
              </div>
            </>
          )}

          {/* Parameters */}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-accent-cyan" />
              <h3 className="text-sm font-semibold text-text-primary">Parameters</h3>
            </div>
            <div className="space-y-2">
              {strategy.params.map((param) => (
                <div
                  key={param.key}
                  className="flex items-center justify-between rounded-lg border border-border-subtle bg-bg-base px-3 py-2"
                >
                  <div>
                    <p className="text-xs font-medium text-text-primary">{param.label}</p>
                    <p className="text-[10px] text-text-muted">
                      {param.type === 'number' && param.min !== undefined && param.max !== undefined
                        ? `Range: ${param.min} – ${param.max}`
                        : param.type === 'boolean'
                        ? 'Toggle'
                        : 'String'}
                    </p>
                  </div>
                  <span className="rounded-md bg-bg-input px-2 py-0.5 font-mono text-xs text-accent-cyan">
                    {renderParamValue(param)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Deploy button */}
          <div className="flex items-center justify-end gap-3 pt-2 border-t border-border-subtle">
            <button
              onClick={onClose}
              className="rounded-md border border-border-subtle bg-bg-input px-4 py-2 text-xs font-medium text-text-secondary hover:bg-bg-elevated hover:text-text-primary transition-colors"
            >
              Close
            </button>
            <button className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-4 py-2 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all">
              <Zap className="h-3.5 w-3.5" />
              Deploy Strategy
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ── Main Page ──
export default function StrategiesPage() {
  const [selected, setSelected] = useState<Strategy | null>(null);

  return (
    <Layout title="Strategies">
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h1 className="text-2xl font-bold text-text-primary">Strategy Library</h1>
          <p className="mt-1 text-sm text-text-muted">
            Click any strategy to learn how it works, see its rules, and deploy it.
          </p>
        </motion.div>

        {/* Strategy Grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {strategies.map((s, i) => (
            <motion.div
              key={s.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <StrategyCard strategy={s} onClick={() => setSelected(s)} />
            </motion.div>
          ))}
        </div>

        {/* Comparison Table */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Performance Comparison</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-border-subtle text-text-muted">
                  <th className="pb-2 font-medium">Strategy</th>
                  <th className="pb-2 font-medium">Category</th>
                  <th className="pb-2 font-medium text-right">Win Rate</th>
                  <th className="pb-2 font-medium text-right">Avg Return</th>
                  <th className="pb-2 font-medium text-right">Sharpe</th>
                  <th className="pb-2 font-medium text-right">Max DD</th>
                  <th className="pb-2 font-medium text-right">Trades</th>
                </tr>
              </thead>
              <tbody className="text-text-secondary">
                {strategies.map((s) => (
                  <tr
                    key={s.id}
                    className="border-b border-border-subtle/50 hover:bg-bg-input/50 transition-colors cursor-pointer"
                    onClick={() => setSelected(s)}
                  >
                    <td className="py-2.5 font-medium text-text-primary">{s.name}</td>
                    <td className="py-2.5">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${categoryColor(s.category).replace('border', '').trim()}`}>
                        {s.category}
                      </span>
                    </td>
                    <td className="py-2.5 text-right font-mono text-success-green">{s.winRate}%</td>
                    <td className="py-2.5 text-right font-mono">{s.avgReturn}%</td>
                    <td className="py-2.5 text-right font-mono">{s.sharpeRatio}</td>
                    <td className="py-2.5 text-right font-mono text-danger-red">{s.maxDrawdown}%</td>
                    <td className="py-2.5 text-right font-mono">{s.tradesCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>
      </div>

      {/* Detail Modal */}
      <AnimatePresence>
        {selected && (
          <StrategyDetail strategy={selected} onClose={() => setSelected(null)} />
        )}
      </AnimatePresence>
    </Layout>
  );
}
