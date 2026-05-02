import type { ReactNode } from 'react';

interface BadgeProps {
  variant?: 'neutral' | 'success' | 'danger' | 'warning' | 'info' | 'cyan';
  children: ReactNode;
  className?: string;
}

const variantStyles = {
  neutral: 'bg-bg-input text-text-secondary border border-border-subtle',
  success: 'bg-success-green-glow text-success-green border border-success-green/30',
  danger: 'bg-danger-red-glow text-danger-red border border-danger-red/30',
  warning: 'bg-warning-amber/10 text-warning-amber border border-warning-amber/30',
  info: 'bg-info-purple/10 text-info-purple border border-info-purple/30',
  cyan: 'bg-accent-cyan-glow text-accent-cyan border border-accent-cyan/30',
};

export default function Badge({ variant = 'neutral', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
