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
import {
  getPortfolio,
  getOrders,
  placeOrder,
  cancelOrder,
  type ApiPortfolio,
  type ApiOrder,
} from '@/lib/api';
import type { Position } from '@/types';

const inputClass =
  'w-full rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan/50 focus:outline-none focus:ring-2 focus:ring-accent-cyan/20';

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
  // Smart price formatter for micro-cap crypto (SHIB / PEPE-tier prices that
  // would otherwise display as ``$0.0000``).
  const formatPrice = (v: number | null | undefined): string => {
    if (v == null || !isFinite(v)) return '—';
    if (Math.abs(v) >= 1) return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (Math.abs(v) >= 0.01) return `$${v.toFixed(4)}`;
    if (Math.abs(v) > 0) return `$${v.toExponential(2)}`;
    return '$0.00';
  };

  // Filter out dust positions — leftover sub-cent remainders from prior
  // sells (size like 7e-9 of GOOGL) that the broker won't accept any
  // close order on. They sit at market_value < $0.01 forever and just
  // clutter the table. The backend ledger still has them; see the
  // /portfolio/{id}/purge-dust endpoint for actual cleanup.
  const DUST_MV_THRESHOLD = 0.01;
  const positions: Position[] =
    portfolio?.positions
      .filter((p) => Math.abs(p.market_value ?? p.size * p.current_price) >= DUST_MV_THRESHOLD)
      .map((p) => ({
      id: p.symbol,
      symbol: p.symbol.replace('-', '/'),
      // Backend serializes ``OrderSide`` as lowercase ('long' / 'short')
      // but the previous strict-uppercase compare bucketed every position
      // as 'short' — the table showed long BUYs with red 'short' badges.
      side: String(p.side ?? '').toLowerCase() === 'long' ? 'long' : 'short',
      size: p.size,
      entryPrice: p.entry_price,
      markPrice: p.current_price,
      pnl: p.unrealized_pnl,
      pnlPercent:
        p.entry_price > 0
          ? ((p.current_price - p.entry_price) / p.entry_price) *
            100 *
            (String(p.side ?? '').toLowerCase() === 'short' ? -1 : 1)
          : 0,
      openedAt: '',
      stopLoss: p.stop_loss,
      takeProfit: p.take_profit,
    })) ?? [];
  const dustCount = (portfolio?.positions.length ?? 0) - positions.length;

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
        <span className={row.side === 'buy' ? 'pill-success' : 'pill-danger'}>
          {row.side.toUpperCase()}
        </span>
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
        <span className="font-mono text-sm tabular-nums text-text-primary">{row.quantity}</span>
      ),
    },
    {
      key: 'price',
      header: 'Price',
      render: (row: ApiOrder) => (
        <span className="font-mono text-sm tabular-nums text-text-primary">
          {row.price ? formatCurrency(row.price) : 'Market'}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: ApiOrder) => (
        <span
          className={
            row.status === 'filled'
              ? 'pill-success'
              : row.status === 'pending'
              ? 'pill-warning'
              : 'pill-neutral'
          }
        >
          {row.status}
        </span>
      ),
    },
    {
      key: 'action',
      header: '',
      render: (row: ApiOrder) =>
        row.status === 'pending' ? (
          <button
            onClick={() => handleCancel(row.id)}
            className="rounded-lg border border-danger-red/30 bg-danger-red/10 p-1.5 text-danger-red transition-colors hover:bg-danger-red/20"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null,
    },
  ];

  return (
    <Layout title="Paper Trading">
      <div className="space-y-6">
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
            className="panel p-5 lg:col-span-1"
          >
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Place Order</h2>
            <form onSubmit={handlePlaceOrder} className="space-y-3">
              <div>
                <label className="stat-label mb-1.5 block">Symbol</label>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  className={`${inputClass} font-mono`}
                />
              </div>

              <div className="flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
                <button
                  type="button"
                  onClick={() => setSide('buy')}
                  className={`flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    side === 'buy'
                      ? 'bg-success-green/15 text-success-green shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  <ArrowUpRight className="mr-1 inline h-3.5 w-3.5" />
                  Buy
                </button>
                <button
                  type="button"
                  onClick={() => setSide('sell')}
                  className={`flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    side === 'sell'
                      ? 'bg-danger-red/15 text-danger-red shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  <ArrowDownRight className="mr-1 inline h-3.5 w-3.5" />
                  Sell
                </button>
              </div>

              <div className="flex items-center gap-0.5 rounded-lg border border-border-subtle bg-bg-input p-0.5">
                <button
                  type="button"
                  onClick={() => setOrderType('market')}
                  className={`flex-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    orderType === 'market'
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  Market
                </button>
                <button
                  type="button"
                  onClick={() => setOrderType('limit')}
                  className={`flex-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    orderType === 'limit'
                      ? 'bg-bg-elevated text-text-primary shadow-card'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  Limit
                </button>
              </div>

              <div>
                <label className="stat-label mb-1.5 block">Quantity</label>
                <input
                  type="number"
                  step="any"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  className={`${inputClass} font-mono tabular-nums`}
                />
              </div>

              {orderType === 'limit' && (
                <div>
                  <label className="stat-label mb-1.5 block">Limit Price</label>
                  <input
                    type="number"
                    step="any"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    placeholder="0.00"
                    className={`${inputClass} font-mono tabular-nums`}
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={placing}
                className={`flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-semibold text-text-inverse transition-colors ${
                  side === 'buy'
                    ? 'bg-success-green hover:bg-success-green/90'
                    : 'bg-danger-red hover:bg-danger-red/90'
                } disabled:opacity-50`}
              >
                {placing ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
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
              <div className="panel p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <Wallet className="h-4 w-4" />
                  <span className="stat-label">Equity</span>
                </div>
                <p className="mt-1.5 font-mono text-xl font-semibold tabular-nums text-text-primary">
                  {formatCurrency(portfolio?.total_equity ?? 0)}
                </p>
              </div>
              <div className="panel p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <TrendingUp className="h-4 w-4" />
                  <span className="stat-label">Unrealized P&L</span>
                </div>
                <p
                  className={`mt-1.5 font-mono text-xl font-semibold tabular-nums ${
                    (portfolio?.unrealized_pnl ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'
                  }`}
                >
                  {(portfolio?.unrealized_pnl ?? 0) >= 0 ? '+' : ''}
                  {formatCurrency(portfolio?.unrealized_pnl ?? 0)}
                </p>
              </div>
              <div className="panel p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <TrendingUp className="h-4 w-4" />
                  <span className="stat-label">Realized P&L</span>
                </div>
                <p
                  className={`mt-1.5 font-mono text-xl font-semibold tabular-nums ${
                    (portfolio?.realized_pnl ?? 0) >= 0 ? 'text-success-green' : 'text-danger-red'
                  }`}
                >
                  {(portfolio?.realized_pnl ?? 0) >= 0 ? '+' : ''}
                  {formatCurrency(portfolio?.realized_pnl ?? 0)}
                </p>
              </div>
              <div className="panel p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <Wallet className="h-4 w-4" />
                  <span className="stat-label">Positions</span>
                </div>
                <p className="mt-1.5 font-mono text-xl font-semibold tabular-nums text-text-primary">
                  {positions.length}
                </p>
              </div>
            </div>

            {/* Positions Table */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 }}
              className="panel p-5"
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-text-primary">Open Positions</h3>
                {dustCount > 0 && (
                  <span
                    className="text-2xs italic text-text-muted"
                    title="Positions with market value < $0.01 — leftover from prior sells the broker won't accept a close order on. Backend purge endpoint can clear them on the next restart."
                  >
                    {dustCount} dust position{dustCount === 1 ? '' : 's'} hidden
                  </span>
                )}
              </div>
              {positions.length === 0 ? (
                <p className="py-8 text-center text-sm text-text-muted">No open positions.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-border-subtle">
                        <th className="stat-label pb-2">Symbol</th>
                        <th className="stat-label pb-2">Side</th>
                        <th className="stat-label pb-2">Size</th>
                        <th className="stat-label pb-2">Entry</th>
                        <th className="stat-label pb-2">Mark</th>
                        <th className="stat-label pb-2">SL</th>
                        <th className="stat-label pb-2">TP</th>
                        <th className="stat-label pb-2">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((p) => (
                        <tr key={p.id} className="border-b border-border-subtle/50">
                          <td className="py-2.5 font-mono text-text-primary">{p.symbol}</td>
                          <td className="py-2.5">
                            <span className={p.side === 'long' ? 'pill-success' : 'pill-danger'}>
                              {p.side}
                            </span>
                          </td>
                          <td className="py-2.5 font-mono tabular-nums text-text-primary">{p.size}</td>
                          <td className="py-2.5 font-mono tabular-nums text-text-secondary">
                            {formatPrice(p.entryPrice)}
                          </td>
                          <td className="py-2.5 font-mono tabular-nums text-text-secondary">
                            {formatPrice(p.markPrice)}
                          </td>
                          <td className="py-2.5 font-mono tabular-nums text-danger-red">
                            {p.stopLoss ? formatPrice(p.stopLoss) : '—'}
                          </td>
                          <td className="py-2.5 font-mono tabular-nums text-success-green">
                            {p.takeProfit ? formatPrice(p.takeProfit) : '—'}
                          </td>
                          <td
                            className={`py-2.5 font-mono tabular-nums ${
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
              className="panel p-5"
            >
              <h3 className="mb-3 text-sm font-semibold text-text-primary">Recent Orders</h3>
              {orders.length === 0 ? (
                <p className="py-8 text-center text-sm text-text-muted">No orders yet.</p>
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
