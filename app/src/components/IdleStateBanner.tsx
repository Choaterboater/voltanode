import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import {
  getEngineStatus,
  getSafetyStatus,
  getStrategies,
  getTrades,
  type ApiStrategy,
} from '@/lib/api';

const RECENT_TRADE_MS = 6 * 60 * 60 * 1000;
const RESTRICTIVE_EXPOSURE_PCT = 100;

function newestTradeAgeMs(trades: { timestamp: string }[]): number | null {
  if (trades.length === 0) return null;
  const newest = trades.reduce((max, t) => {
    const ts = new Date(t.timestamp).getTime();
    return ts > max ? ts : max;
  }, 0);
  return Date.now() - newest;
}

function buildReasons(opts: {
  restrictive: boolean;
  maxExposure: number;
  killSwitch: boolean;
  noRecentTrades: boolean;
  registeredCount: number;
  activeCount: number;
}): string[] {
  const reasons: string[] = [];
  if (opts.killSwitch) reasons.push('Kill switch is active — engine ticks are blocked.');
  if (opts.restrictive) {
    reasons.push(
      `Exposure cap is ${opts.maxExposure}% (paper mode usually uses ~300%). BUYs may be rejected.`,
    );
  }
  if (opts.noRecentTrades && opts.registeredCount > 0) {
    if (opts.activeCount === 0) {
      reasons.push(`${opts.registeredCount} bot(s) registered but none are active.`);
    } else {
      reasons.push(
        `${opts.activeCount} active bot(s) but no fills in the last 6 hours — signals may be on hold or gated.`,
      );
    }
  }
  return reasons;
}

export default function IdleStateBanner() {
  const [reasons, setReasons] = useState<string[]>([]);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [engine, safety, stratsRes, trades] = await Promise.all([
          getEngineStatus(),
          getSafetyStatus(),
          getStrategies(),
          getTrades(30),
        ]);
        if (cancelled || !engine.running) {
          setVisible(false);
          return;
        }

        const limits = safety.safety_limits;
        const maxExposure = Number(limits.max_exposure_pct ?? 500);
        const restrictive = maxExposure < RESTRICTIVE_EXPOSURE_PCT;
        const killSwitch = safety.kill_switch?.activated === true;
        const ageMs = newestTradeAgeMs(trades);
        const noRecentTrades = ageMs === null || ageMs > RECENT_TRADE_MS;
        const strategies: ApiStrategy[] = stratsRes.strategies;
        const activeCount = strategies.filter(s => s.is_active).length;

        const next = buildReasons({
          restrictive,
          maxExposure,
          killSwitch,
          noRecentTrades,
          registeredCount: strategies.length,
          activeCount,
        });

        setReasons(next);
        setVisible(next.length > 0);
      } catch {
        if (!cancelled) setVisible(false);
      }
    }

    load();
    const interval = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (!visible || reasons.length === 0) return null;

  return (
    <div
      className="panel flex gap-3 border-warning-amber/30 bg-warning-amber/5 p-4"
      role="status"
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning-amber" aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-semibold text-text-primary">Bots may be idle</p>
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-text-secondary">
          {reasons.map(r => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
