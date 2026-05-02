import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Wallet,
  TrendingUp,
  Plus,
  Target,
  Loader2,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';
import { usePortfolio } from '@/hooks/useApi';
import { toast } from 'sonner';

export default function PaperTrading() {
  const { data: portfolio, loading, refresh } = usePortfolio();
  const [showTrade, setShowTrade] = useState(false);
  const [trade, setTrade] = useState({ symbol: 'BTC/USD', side: 'buy' as 'buy' | 'sell', quantity: '0.1', price: '' });

  const submitTrade = async () => {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/orders/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: trade.symbol,
          side: trade.side,
          order_type: trade.price ? 'limit' : 'market',
          quantity: parseFloat(trade.quantity),
          price: trade.price ? parseFloat(trade.price) : undefined,
          account_id: 'default',
        }),
      });
      if (!res.ok) throw new Error('Order failed');
      toast.success(`${trade.side.toUpperCase()} order submitted`);
      setShowTrade(false);
      refresh();
    } catch {
      toast.error('Order failed. Check balance and try again.');
    }
  };

  const balances = portfolio?.balances || {};
  const positions = portfolio?.positions || [];
  const totalEquity = portfolio?.total_equity || Object.values(balances).reduce((a, b) => a + b, 0);

  return (
    <Layout title="Paper Trading">
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Metrics */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <div className="flex items-center gap-2">
              <Wallet className="h-4 w-4 text-accent-cyan" />
              <p className="text-xs text-text-muted">Virtual Balance</p>
            </div>
            <p className="mt-2 font-mono text-xl font-semibold text-text-primary">
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : `$${(balances['USDT'] || 10000).toLocaleString()}`}
            </p>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-success-green" />
              <p className="text-xs text-text-muted">Total Equity</p>
            </div>
            <p className="mt-2 font-mono text-xl font-semibold text-text-primary">
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : `$${totalEquity.toLocaleString()}`}
            </p>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <div className="flex items-center gap-2">
              <Target className="h-4 w-4 text-warning-amber" />
              <p className="text-xs text-text-muted">Open Positions</p>
            </div>
            <p className="mt-2 font-mono text-xl font-semibold text-text-primary">{positions.length}</p>
          </motion.div>
        </div>

        {/* Trade Form */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-text-primary">Positions</h2>
            <button
              onClick={() => setShowTrade(!showTrade)}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
            >
              <Plus className="h-3.5 w-3.5" />
              New Trade
            </button>
          </div>
        </motion.div>

        {showTrade && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-[10px] border border-border-subtle bg-bg-surface p-5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <input
                placeholder="Symbol"
                value={trade.symbol}
                onChange={(e) => setTrade({ ...trade, symbol: e.target.value })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary focus:border-accent-cyan focus:outline-none"
              />
              <select
                value={trade.side}
                onChange={(e) => setTrade({ ...trade, side: e.target.value as 'buy' | 'sell' })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary focus:border-accent-cyan focus:outline-none"
              >
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
              <input
                placeholder="Quantity"
                value={trade.quantity}
                onChange={(e) => setTrade({ ...trade, quantity: e.target.value })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary focus:border-accent-cyan focus:outline-none"
              />
              <input
                placeholder="Limit price (optional)"
                value={trade.price}
                onChange={(e) => setTrade({ ...trade, price: e.target.value })}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button onClick={submitTrade} className="rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all">
                Submit Order
              </button>
              <button onClick={() => setShowTrade(false)} className="rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-elevated transition-colors">
                Cancel
              </button>
            </div>
          </motion.div>
        )}

        {/* Positions Table */}
        {positions.length > 0 ? (
          <div className="rounded-[10px] border border-border-subtle bg-bg-surface overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-bg-input text-text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Symbol</th>
                  <th className="px-4 py-2 font-medium">Side</th>
                  <th className="px-4 py-2 font-medium">Size</th>
                  <th className="px-4 py-2 font-medium">Entry</th>
                  <th className="px-4 py-2 font-medium">Current</th>
                  <th className="px-4 py-2 font-medium text-right">P&L</th>
                </tr>
              </thead>
              <tbody className="text-text-secondary">
                {positions.map((pos) => (
                  <tr key={pos.symbol} className="border-t border-border-subtle">
                    <td className="px-4 py-3 font-medium text-text-primary">{pos.symbol}</td>
                    <td className="px-4 py-3">
                      <Badge variant={pos.side === 'long' ? 'success' : 'danger'}>{pos.side}</Badge>
                    </td>
                    <td className="px-4 py-3 font-mono">{pos.size}</td>
                    <td className="px-4 py-3 font-mono">${pos.entry_price?.toLocaleString()}</td>
                    <td className="px-4 py-3 font-mono">${pos.current_price?.toLocaleString()}</td>
                    <td className={`px-4 py-3 text-right font-mono ${(pos.unrealized_pnl || 0) >= 0 ? 'text-success-green' : 'text-danger-red'}`}>
                      {(pos.unrealized_pnl || 0) >= 0 ? '+' : ''}${(pos.unrealized_pnl || 0).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex h-32 items-center justify-center rounded-[10px] border border-border-subtle bg-bg-surface">
            <p className="text-sm text-text-muted">No open positions. Submit a trade to get started.</p>
          </div>
        )}
      </div>
    </Layout>
  );
}
