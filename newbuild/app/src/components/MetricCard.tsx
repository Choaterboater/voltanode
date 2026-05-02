import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: string | number;
  deltaPositive?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
  delay?: number;
}

export default function MetricCard({
  label,
  value,
  delta,
  deltaPositive = true,
  icon,
  children,
  delay = 0,
}: MetricCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay,
        ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
      }}
      className="rounded-[10px] border border-border-subtle bg-bg-surface p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-cyan/20"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-text-muted">{label}</p>
          <p className="mt-1 font-mono text-xl font-medium tabular-nums text-text-primary">
            {value}
          </p>
          {delta !== undefined && (
            <p
              className={`mt-1 text-xs font-mono tabular-nums ${
                deltaPositive ? 'text-success-green' : 'text-danger-red'
              }`}
            >
              {deltaPositive && typeof delta === 'string' && !delta.startsWith('+') ? '+' : ''}
              {delta}
            </p>
          )}
        </div>
        {icon && (
          <div className="text-text-muted">{icon}</div>
        )}
      </div>
      {children && <div className="mt-3">{children}</div>}
    </motion.div>
  );
}
