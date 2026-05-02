import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowUpRight,
  ArrowDownRight,
  Send,
  X,
  Wallet,
  TrendingUp,
} from 'lucide-react';
import Layout from '@/components/Layout';
import DataTable from '@/components/DataTable';
import Badge from '@/components/Badge';
import {
  getPortfolio,
  getOrders,
  placeOrder,
  cancelOrder,
  type ApiPortfolio,
  type ApiOrder,
} from '@/lib/api';
import type { Position } from '@/types';

export default function PaperTrading() {
  const [portfolio, setPortfolio] = useState<ApiPortfolio | null>(null);
  const [orders, setOrders] = useState<ApiOrder[]>([]);
  const [, setLoading] = useState(true);
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Order form state
  const [symbol, setSymbol] = useState('BTC-USD');
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market');
  const [quantity, setQuantity] = useState('0.1');
  const [price, setPrice] = useState('');

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, []);

  async function loadData() {
    try {
      const [portRes, orderRes] = await Promise.all([getPortfolio(), getOrders()]);
      setPortfolio(portRes);
      setOrders(orderRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }

  async function handlePlaceOrder(e: React.FormEvent) {
    e.preventDefault();
    try {
      setPlacing(true);
      setError(null);
      await placeOrder({
        symbol,
        side,
        order_type: orderType,
        quantity: parseFloat(quantity),
        price: orderType === 'limit' ? parseFloat(price) : undefined,
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Order failed');
    } finally {
      setPlacing(false);
    }
  }

  async function handleCancel(orderId: string) {
    try {
      await cancelOrder(orderId);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cancel failed');
    }
  }

  const formatCurrency = (v: number) =>
    `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const positions: Position[] =
    portfolio?.positions.map((p) => ({
      id: p.symbol,
      symbol: p.symbol.replace('-', '/'),
      side: p.side === 'LONG' ? 'long' : 'short',
      size: p.size,
      entryPrice: p.entry_price,
      markPrice: p.current_price,
      pnl: p.unrealized_pnl,
      pnlPercent:
        p.entry_price > 0
          ? ((p.current_price - p.entry_price) / p.entry_price) * 100 * (p.side === 'SHORT' ? -1 : 1)
          : 0,
      openedAt: '',
    })) ?? [];

  const orderColumns = [
    {
      key: 'symbol',
      header: 'Symbol',
      render: (row: ApiOrder) => (
        <span className="font-mono text-sm text-text-primary">{row.symbol.replace('-', '/')}</span>
      ),
    },
    {
      key: 'side',
      header: 'Side',
      render: (row: ApiOrder) => (
        <Badge variant={row.side === 'buy' ? 'success' : 'danger'}>
          {row.side.toUpperCase()}
        </Badge>
      ),
    },
    {
      key: 'type',
      header: 'Type',
      render: (row: ApiOrder) => (
        <span className="text-xs text-text-secondary capitalize">{row.order_type}</span>
      ),
    },
    {
      key: 'qty',
      header: 'Qty',
      render: (row: ApiOrder) => (
        <span className="font-mono text-sm text-text-primary">{row.quantity}</span>
      ),
    },
    {
      key: 'price',
      header: 'Price',
      render: (row: ApiOrder) => (
        <span className="font-mono text-sm text-text-primary">
          {row.price ? formatCurrency(row.price) : 'Market'}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: ApiOrder) => (
        <Badge
          variant={
            row.status === 'filled'
              ? 'success'
              : row.status === 'pending'
              ? 'warning'
              : 'neutral'
          }
        >
          {row.status}
        </Badge>
      ),
    },
    {
      key: 'action',
      header: '',
      render: (row: ApiOrder) =>
        row.status === 'pending' ? (
          <button
            onClick={() => handleCancel(row.id)}
            className="rounded-md p-1.5 text-danger-red hover:bg-danger-red/10 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null,
    },
  ];

  return (
    <Layout title="Paper Trading">
      <div className="space-y-5">
        {error && (
          <div className="rounded-lg border border-danger-red/30 bg-danger-red/10 px-4 py-2 text-sm text-danger-red">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 xl:gap-5">
          {/* Order Entry */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-[10px] border border-border-subtle bg-bg-surface p-5 lg:col-span-1"
          >
            <h2 className="mb-4 text-base font-semibold text-text-primary">Place Order</h2>
            <form onSubmit={handlePlaceOrder} className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-text-muted">Symbol</label>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                />
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSide('buy')}
                  className={`flex-1 rounded-md py-2 text-xs font-medium transition-colors ${
                    side === 'buy'
                      ? 'bg-success-green/20 text-success-green'
                      : 'bg-bg-input text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <ArrowUpRight className="mr-1 inline h-3.5 w-3.5" />
                  Buy
                </button>
                <button
                  type="button"
                  onClick={() => setSide('sell')}
                  className={`flex-1 rounded-md py-2 text-xs font-medium transition-colors ${
                    side === 'sell'
                      ? 'bg-danger-red/20 text-danger-red'
                      : 'bg-bg-input text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <ArrowDownRight className="mr-1 inline h-3.5 w-3.5" />
                  Sell
                </button>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setOrderType('market')}
                  className={`flex-1 rounded-md py-1.5 text-xs font-medium transition-colors ${
                    orderType === 'market'
                      ? 'bg-accent-cyan/20 text-accent-cyan'
                      : 'bg-bg-input text-text-secondary'
                  }`}
                >
                  Market
                </button>
                <button
                  type="button"
                  onClick={() => setOrderType('limit')}
                  className={`flex-1 rounded-md py-1.5 text-xs font-medium transition-colors ${
                    orderType === 'limit'
                      ? 'bg-accent-cyan/20 text-accent-cyan'
                      : 'bg-bg-input text-text-secondary'
                  }`}
                >
                  Limit
                </button>
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">Quantity</label>
                <input
                  type="number"
                  step="any"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                />
              </div>

              {orderType === 'limit' && (
                <div>
                  <label className="mb-1 block text-xs text-text-muted">Limit Price</label>
                  <input
                    type="number"
                    step="any"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    placeholder="0.00"
                    className="w-full rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan"
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={placing}
                className={`flex w-full items-center justify-center gap-2 rounded-md py-2.5 text-sm font-semibold text-text-inverse transition-colors ${
                  side === 'buy' ? 'bg-success-green hover:brightness-110' : 'bg-danger-red hover:brightness-110'
                } disabled:opacity-50`}
              >
                {placing ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                {side === 'buy' ? 'Place Buy Order' : 'Place Sell Order'}
              </button>
            </form>
          </motion.div>

          {/* Portfolio + Positions */}
          <div className="space-y-4 lg:col-span-2">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <Wallet className="h-4 w-4" />
                  <span className="text-xs">Equity</span>
                </div>
                <p className="mt-1 font-mono text-lg text-text-primary">
                  {formatCurrency(portfolio?.total_equity ?? 0)}
                </p>
              </div>
              <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <TrendingUp className="h-4 w-4" />
                  <span className="text-xs">Unrealized P&L</span>
                </div>
                <p
                  className={`mt-1 font-mono text-lg ${
                    (portfolio?.unrealized_pnl ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'
                  }`}
                >
                  {(portfolio?.unrealized_pnl ?? 0) >= 0 ? '+' : ''}
                  {formatCurrency(portfolio?.unrealized_pnl ?? 0)}
                </p>
              </div>
              <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <TrendingUp className="h-4 w-4" />
                  <span className="text-xs">Realized P&L</span>
                </div>
                <p
                  className={`mt-1 font-mono text-lg ${
                    (portfolio?.realized_pnl ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'
                  }`}
                >
                  {(portfolio?.realized_pnl ?? 0) >= 0 ? '+' : ''}
                  {formatCurrency(portfolio?.realized_pnl ?? 0)}
                </p>
              </div>
              <div className="rounded-[10px] border border-border-subtle bg-bg-surface p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <Wallet className="h-4 w-4" />
                  <span className="text-xs">Positions</span>
                </div>
                <p className="mt-1 font-mono text-lg text-text-primary">{positions.length}</p>
              </div>
            </div>

            {/* Positions Table */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
            >
              <h3 className="mb-3 text-sm font-semibold text-text-primary">Open Positions</h3>
              {positions.length === 0 ? (
                <p className="text-sm text-text-muted">No open positions.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-border-subtle text-xs text-text-muted">
                        <th className="pb-2 font-medium">Symbol</th>
                        <th className="pb-2 font-medium">Side</th>
                        <th className="pb-2 font-medium">Size</th>
                        <th className="pb-2 font-medium">Entry</th>
                        <th className="pb-2 font-medium">Mark</th>
                        <th className="pb-2 font-medium">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((p) => (
                        <tr key={p.id} className="border-b border-border-subtle/50">
                          <td className="py-2 font-mono text-text-primary">{p.symbol}</td>
                          <td className="py-2">
                            <Badge variant={p.side === 'long' ? 'success' : 'danger'}>
                              {p.side}
                            </Badge>
                          </td>
                          <td className="py-2 font-mono text-text-primary">{p.size}</td>
                          <td className="py-2 font-mono text-text-secondary">
                            {formatCurrency(p.entryPrice)}
                          </td>
                          <td className="py-2 font-mono text-text-secondary">
                            {formatCurrency(p.markPrice)}
                          </td>
                          <td
                            className={`py-2 font-mono ${
                              p.pnl >= 0 ? 'text-success-green' : 'text-danger-red'
                            }`}
                          >
                            {p.pnl >= 0 ? '+' : ''}
                            {formatCurrency(p.pnl)} ({p.pnlPercent.toFixed(2)}%)
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </motion.div>

            {/* Orders */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
            >
              <h3 className="mb-3 text-sm font-semibold text-text-primary">Recent Orders</h3>
              {orders.length === 0 ? (
                <p className="text-sm text-text-muted">No orders yet.</p>
              ) : (
                <DataTable
                  columns={orderColumns}
                  data={orders.slice(0, 10)}
                  keyExtractor={(row) => row.id}
                />
              )}
            </motion.div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
