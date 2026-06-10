import type { ReactNode } from 'react';

interface BadgeProps {
  variant?: 'neutral' | 'success' | 'danger' | 'warning' | 'info' | 'cyan';
  children: ReactNode;
  className?: string;
}

const variantStyles = {
  neutral: 'bg-bg-elevated/80 text-text-secondary',
  success: 'bg-success-green/10 text-success-green',
  danger: 'bg-danger-red/10 text-danger-red',
  warning: 'bg-warning-amber/10 text-warning-amber',
  info: 'bg-info-purple/10 text-info-purple',
  cyan: 'bg-accent-cyan/10 text-accent-cyan',
};

export default function Badge({ variant = 'neutral', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-2xs font-semibold ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
