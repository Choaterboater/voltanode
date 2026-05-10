import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

type DeltaTone = 'auto' | 'positive' | 'negative' | 'neutral';

interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: string | number;
  /**
   * Color hint for the delta line.
   *  - "auto" (default): green if ``deltaPositive`` else red. Use this for
   *    P&L / change metrics where direction has meaning.
   *  - "neutral": muted grey. Use for descriptive deltas like
   *    "5 long / 1 short" or "10 closed" — direction-less labels.
   *  - "positive" / "negative": explicit color override.
   */
  deltaTone?: DeltaTone;
  deltaPositive?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
  delay?: number;
}

export default function MetricCard({
  label,
  value,
  delta,
  deltaTone = 'auto',
  deltaPositive = true,
  icon,
  children,
  delay = 0,
}: MetricCardProps) {
  // Resolve delta color from tone + positivity
  const tone: DeltaTone =
    deltaTone === 'auto' ? (deltaPositive ? 'positive' : 'negative') : deltaTone;
  const deltaColor =
    tone === 'positive'
      ? 'text-success-green'
      : tone === 'negative'
        ? 'text-danger-red'
        : 'text-text-muted';

  // Auto-prepend "+" only for numeric-looking positive deltas — not for
  // descriptive labels like "5 long / 1 short" or "10 closed".
  const deltaStr = delta !== undefined ? String(delta) : '';
  const isNumericLooking = /^-?\d/.test(deltaStr);
  const showPlus =
    tone === 'positive' &&
    isNumericLooking &&
    !deltaStr.startsWith('+') &&
    !deltaStr.startsWith('-');

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay,
        ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
      }}
      // h-full so all cards in a grid row equalize even when their child
      // bodies have different heights (sparkline vs donut vs progress bars).
      // flex column keeps the child block pinned to the bottom.
      className="flex h-full flex-col rounded-[10px] border border-border-subtle bg-bg-surface p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-cyan/20"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-text-muted">{label}</p>
          <p className="mt-1 font-mono text-xl font-medium tabular-nums text-text-primary">
            {value}
          </p>
          {delta !== undefined && (
            <p className={`mt-1 text-xs font-mono tabular-nums ${deltaColor}`}>
              {showPlus ? '+' : ''}
              {delta}
            </p>
          )}
        </div>
        {icon && <div className="shrink-0 text-text-muted">{icon}</div>}
      </div>
      {children && <div className="mt-3 flex-1">{children}</div>}
    </motion.div>
  );
}
