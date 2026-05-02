import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Play,
  Pause,
  Square,
  Plus,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';
import { useEngineStatus } from '@/hooks/useApi';
import { toast } from 'sonner';

interface BotConfig {
  id: string;
  name: string;
  strategy: string;
  symbol: string;
  status: 'running' | 'paused' | 'stopped';
  pnl: number;
  pnlPercent: number;
  uptime: string;
}

const mockBots: BotConfig[] = [
  { id: 'bot-1', name: 'Momentum Bot', strategy: 'Momentum', symbol: 'BTC/USD', status: 'running', pnl: 1247.5, pnlPercent: 8.45, uptime: '2d 14h' },
  { id: 'bot-2', name: 'Grid Bot', strategy: 'Grid', symbol: 'ETH/USD', status: 'running', pnl: 892.1, pnlPercent: 6.12, uptime: '5d 3h' },
  { id: 'bot-3', name: 'Mean Reversion', strategy: 'Mean Reversion', symbol: 'SOL/USD', status: 'paused', pnl: -234.2, pnlPercent: -3.18, uptime: 'Paused 3h ago' },
  { id: 'bot-4', name: 'Breakout Bot', strategy: 'Breakout', symbol: 'AVAX/USD', status: 'stopped', pnl: 456.75, pnlPercent: 4.82, uptime: 'Stopped 12h ago' },
];

const strategies = ['Momentum', 'Mean Reversion', 'Grid', 'Breakout', 'MACD', 'Arbitrage', 'ML Ensemble'];

export default function BotLab() {
  const { status, loading: engineLoading, refresh, startEngine, stopEngine } = useEngineStatus();
  const [bots, setBots] = useState<BotConfig[]>(mockBots);
  const [showCreate, setShowCreate] = useState(false);
  const [newBot, setNewBot] = useState({ name: '', strategy: 'Momentum', symbol: 'BTC/USD' });

  useEffect(() => {
    refresh();
  }, [refresh]);

  const toggleBot = (id: string) => {
    setBots((prev) =>
      prev.map((b) => {
        if (b.id !== id) return b;
        const nextStatus = b.status === 'running' ? 'paused' : b.status === 'paused' ? 'running' : 'running';
        toast.success(`${b.name} ${nextStatus === 'running' ? 'started' : 'paused'}`);
        return { ...b, status: nextStatus };
      })
    );
  };

  const stopBot = (id: string) => {
    setBots((prev) =>
      prev.map((b) => {
        if (b.id !== id) return b;
        toast.info(`${b.name} stopped`);
        return { ...b, status: 'stopped' };
      })
    );
  };

  const createBot = () => {
    if (!newBot.name.trim()) {
      toast.error('Bot name is required');
      return;
    }
    const bot: BotConfig = {
      id: `bot-${Date.now()}`,
      name: newBot.name,
      strategy: newBot.strategy,
      symbol: newBot.symbol,
      status: 'running',
      pnl: 0,
      pnlPercent: 0,
      uptime: 'Just started',
    };
    setBots((prev) => [bot, ...prev]);
    setShowCreate(false);
    setNewBot({ name: '', strategy: 'Momentum', symbol: 'BTC/USD' });
    toast.success(`${bot.name} deployed`);
  };

  const topBarRight = (
    <div className="flex items-center gap-2">
      <Badge variant={status?.running ? 'success' : 'warning'}>
        {status?.running ? 'Engine Running' : 'Engine Stopped'}
      </Badge>
      {status?.running ? (
        <button onClick={stopEngine} disabled={engineLoading} className="rounded-md border border-border-subtle bg-bg-input px-2 py-1 text-xs text-text-secondary hover:bg-bg-elevated transition-colors">
          Stop Engine
        </button>
      ) : (
        <button onClick={startEngine} disabled={engineLoading} className="rounded-md bg-accent-cyan px-2 py-1 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all">
          Start Engine
        </button>
      )}
    </div>
  );

  return (
    <Layout title="Bot Lab" rightContent={topBarRight}>
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Create Bot */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-text-primary">Active Bots</h2>
            <button
              onClick={() => setShowCreate(!showCreate)}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
            >
              <Plus className="h-3.5 w-3.5" />
              New Bot
            </button>
          </div>
        </motion.div>

        {showCreate && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
          >
            <h3 className="text-sm font-semibold text-text-primary mb-3">Deploy New Bot</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <input
                placeholder="Bot name"
                value={newBot.name}
                onChange={(e) => setNewBot({ ...newBot, name: e.target.value })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
              <select
                value={newBot.strategy}
                onChange={(e) => setNewBot({ ...newBot, strategy: e.target.value })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary focus:border-accent-cyan focus:outline-none"
              >
                {strategies.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <input
                placeholder="Symbol (e.g. BTC/USD)"
                value={newBot.symbol}
                onChange={(e) => setNewBot({ ...newBot, symbol: e.target.value })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button onClick={createBot} className="rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all">
                Deploy
              </button>
              <button onClick={() => setShowCreate(false)} className="rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-elevated transition-colors">
                Cancel
              </button>
            </div>
          </motion.div>
        )}

        {/* Bot Grid */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {bots.map((bot, i) => (
            <motion.div
              key={bot.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
            >
              <div className="flex items-start justify-between">
                <div>
                  <Badge variant={bot.status === 'running' ? 'success' : bot.status === 'paused' ? 'warning' : 'danger'}>
                    {bot.status}
                  </Badge>
                  <h3 className="mt-2 text-sm font-semibold text-text-primary">{bot.name}</h3>
                  <p className="text-xs text-text-muted">{bot.strategy} · {bot.symbol}</p>
                </div>
                <div className="text-right">
                  <p className={`font-mono text-sm font-medium ${bot.pnl >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
                    {bot.pnl >= 0 ? '+' : ''}${bot.pnl.toLocaleString()}
                  </p>
                  <p className="text-xs text-text-muted">{bot.uptime}</p>
                </div>
              </div>

              <div className="mt-4 flex items-center gap-2">
                {bot.status === 'running' ? (
                  <button onClick={() => toggleBot(bot.id)} className="rounded-md p-1.5 text-text-secondary hover:bg-bg-input hover:text-text-primary transition-colors">
                    <Pause className="h-4 w-4" />
                  </button>
                ) : (
                  <button onClick={() => toggleBot(bot.id)} className="rounded-md p-1.5 text-success-green hover:bg-success-green-glow transition-colors">
                    <Play className="h-4 w-4" />
                  </button>
                )}
                <button onClick={() => stopBot(bot.id)} className="rounded-md p-1.5 text-danger-red hover:bg-danger-red-glow transition-colors">
                  <Square className="h-4 w-4" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </Layout>
  );
}
