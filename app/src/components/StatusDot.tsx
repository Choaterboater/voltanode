interface StatusDotProps {
  status: 'running' | 'stopped' | 'paused' | 'error';
  className?: string;
}

const statusColors = {
  running: 'bg-success-green',
  stopped: 'bg-text-muted',
  paused: 'bg-warning-amber',
  error: 'bg-danger-red',
};

export default function StatusDot({ status, className = '' }: StatusDotProps) {
  const isPulsing = status === 'running' || status === 'paused';
  return (
    <span className={`relative inline-flex h-2.5 w-2.5 ${className}`}>
      <span
        className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${statusColors[status]} ${isPulsing ? 'animate-pulse-dot' : ''}`}
      />
      <span
        className={`relative inline-flex h-2.5 w-2.5 rounded-full ${statusColors[status]}`}
      />
    </span>
  );
}
