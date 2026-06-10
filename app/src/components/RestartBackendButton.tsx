import { useEffect, useState } from 'react';
import { restartBackend, getEngineStatus } from '../lib/api';

/** Top-right restart button. Click → confirm → POST /settings/restart →
 *  show reconnecting spinner → poll /engine/status until backend comes
 *  back. Whole cycle is ~5-8s in practice. */
export default function RestartBackendButton() {
  const [state, setState] = useState<'idle' | 'confirming' | 'restarting' | 'done'>('idle');

  useEffect(() => {
    if (state !== 'restarting') return;
    let cancelled = false;
    let attempts = 0;
    const poll = async () => {
      while (!cancelled && attempts < 60) {
        attempts++;
        try {
          await new Promise((r) => setTimeout(r, 1000));
          const s = await getEngineStatus();
          if (s.running) {
            setState('done');
            setTimeout(() => setState('idle'), 2500);
            return;
          }
        } catch {
          // backend still down, keep polling
        }
      }
      if (!cancelled) setState('idle'); // gave up — go back to idle
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [state]);

  const onClick = async () => {
    if (state === 'idle') {
      setState('confirming');
      return;
    }
    if (state === 'confirming') {
      setState('restarting');
      try {
        await restartBackend();
      } catch {
        // The restart endpoint usually returns before being killed, but
        // a hard race can drop the response. Either way, fall through to
        // polling — that's the source of truth.
      }
    }
  };

  const label =
    state === 'idle'
      ? 'Restart backend'
      : state === 'confirming'
        ? 'Click again to confirm'
        : state === 'restarting'
          ? 'Restarting…'
          : 'Back up ✓';

  const tone =
    state === 'confirming'
      ? 'border-warning-amber/40 text-warning-amber hover:bg-warning-amber/10'
      : state === 'restarting'
        ? 'border-border-subtle text-text-muted cursor-wait'
        : state === 'done'
          ? 'border-success-green/40 text-success-green'
          : 'border-border-subtle text-text-secondary hover:border-accent-cyan/30 hover:text-text-primary';

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={state === 'restarting' || state === 'done'}
      className={`inline-flex items-center gap-1.5 rounded-lg border bg-bg-elevated/60 px-3 py-1.5 text-xs font-medium transition-colors ${tone}`}
      title="Stops the running backend process and starts a fresh one in a new console."
    >
      {state === 'restarting' && (
        <span className="h-2 w-2 animate-pulse rounded-full bg-warning-amber" />
      )}
      {label}
    </button>
  );
}
