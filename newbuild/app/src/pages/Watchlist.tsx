import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Sparkles,
  Search,
  Plus,
  X,
  ArrowRight,
} from 'lucide-react';
import Layout from '@/components/Layout';
import Badge from '@/components/Badge';

interface WatchItem {
  symbol: string;
  name: string;
  category: 'crypto' | 'stock';
  price: number;
  change24h: number;
  recommendation: 'strong_buy' | 'buy' | 'hold' | 'sell' | 'strong_sell';
  reason: string;
}

const defaultCrypto: WatchItem[] = [
  { symbol: 'BTC/USD', name: 'Bitcoin', category: 'crypto', price: 97420, change24h: 2.4, recommendation: 'buy', reason: 'Breaking above key resistance with strong volume' },
  { symbol: 'ETH/USD', name: 'Ethereum', category: 'crypto', price: 3650, change24h: 1.8, recommendation: 'buy', reason: 'ETF inflows accelerating; network activity high' },
  { symbol: 'SOL/USD', name: 'Solana', category: 'crypto', price: 198, change24h: 5.2, recommendation: 'strong_buy', reason: 'DeFi TVL at ATH; developer activity surging' },
  { symbol: 'ADA/USD', name: 'Cardano', category: 'crypto', price: 1.12, change24h: -0.8, recommendation: 'hold', reason: 'Consolidating after upgrade; wait for breakout' },
  { symbol: 'LINK/USD', name: 'Chainlink', category: 'crypto', price: 21.40, change24h: 3.1, recommendation: 'buy', reason: 'Cross-chain interoperability demand growing' },
  { symbol: 'AVAX/USD', name: 'Avalanche', category: 'crypto', price: 42.80, change24h: -1.2, recommendation: 'hold', reason: 'Subnet adoption steady but competition rising' },
  { symbol: 'DOT/USD', name: 'Polkadot', category: 'crypto', price: 7.50, change24h: 0.5, recommendation: 'hold', reason: 'Parachain ecosystem maturing; flat price action' },
  { symbol: 'POL/USD', name: 'Polygon', category: 'crypto', price: 0.52, change24h: 4.5, recommendation: 'buy', reason: 'POL migration complete; ZK rollup narrative' },
  { symbol: 'DOGE/USD', name: 'Dogecoin', category: 'crypto', price: 0.18, change24h: -2.1, recommendation: 'sell', reason: 'Meme fatigue; declining social sentiment' },
  { symbol: 'XRP/USD', name: 'XRP', category: 'crypto', price: 2.35, change24h: 1.2, recommendation: 'hold', reason: 'Legal clarity priced in; watch for ETF news' },
];

const defaultStocks: WatchItem[] = [
  { symbol: 'AAPL', name: 'Apple', category: 'stock', price: 228.50, change24h: 0.9, recommendation: 'buy', reason: 'iPhone cycle + services growth; strong cash flow' },
  { symbol: 'NVDA', name: 'NVIDIA', category: 'stock', price: 142.20, change24h: 3.5, recommendation: 'strong_buy', reason: 'AI datacenter demand insatiable; Blackwell ramping' },
  { symbol: 'TSLA', name: 'Tesla', category: 'stock', price: 345.80, change24h: -1.4, recommendation: 'hold', reason: 'Robotaxi optimism vs. delivery uncertainty' },
  { symbol: 'MSFT', name: 'Microsoft', category: 'stock', price: 432.10, change24h: 1.1, recommendation: 'buy', reason: 'Azure + Copilot monetization accelerating' },
  { symbol: 'AMZN', name: 'Amazon', category: 'stock', price: 198.40, change24h: 0.7, recommendation: 'buy', reason: 'AWS margins expanding; retail efficiency gains' },
  { symbol: 'META', name: 'Meta', category: 'stock', price: 595.20, change24h: 2.2, recommendation: 'buy', reason: 'Reels monetization + AI glasses narrative' },
  { symbol: 'AMD', name: 'AMD', category: 'stock', price: 138.90, change24h: -0.5, recommendation: 'hold', reason: 'MI300 gaining share but valuation stretched' },
  { symbol: 'GOOGL', name: 'Alphabet', category: 'stock', price: 178.30, change24h: 0.4, recommendation: 'buy', reason: 'Search moat intact; Gemini improving rapidly' },
  { symbol: 'NFLX', name: 'Netflix', category: 'stock', price: 785.60, change24h: 1.8, recommendation: 'buy', reason: 'Ad tier scaling; password-sharing crackdown working' },
  { symbol: 'CRM', name: 'Salesforce', category: 'stock', price: 288.40, change24h: -0.9, recommendation: 'hold', reason: 'Agentforce promising but execution risk remains' },
];

function recBadge(rec: WatchItem['recommendation']) {
  const map: Record<string, { label: string; variant: 'success' | 'danger' | 'warning' | 'neutral' }> = {
    strong_buy: { label: 'Strong Buy', variant: 'success' },
    buy: { label: 'Buy', variant: 'success' },
    hold: { label: 'Hold', variant: 'warning' },
    sell: { label: 'Sell', variant: 'danger' },
    strong_sell: { label: 'Strong Sell', variant: 'danger' },
  };
  const m = map[rec] || { label: rec, variant: 'default' };
  return <Badge variant={m.variant}>{m.label}</Badge>;
}

function trendIcon(change: number) {
  if (change > 1) return <TrendingUp className="h-4 w-4 text-success-green" />;
  if (change < -1) return <TrendingDown className="h-4 w-4 text-danger-red" />;
  return <Minus className="h-4 w-4 text-text-muted" />;
}

export default function Watchlist() {
  const [tab, setTab] = useState<'crypto' | 'stock'>('crypto');
  const [query, setQuery] = useState('');
  const [customItems, setCustomItems] = useState<WatchItem[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const navigate = useNavigate();

  const baseList = tab === 'crypto' ? defaultCrypto : defaultStocks;
  const allItems = [...baseList, ...customItems.filter((i) => i.category === tab)];

  const filtered = query.trim()
    ? allItems.filter(
        (i) =>
          i.symbol.toLowerCase().includes(query.toLowerCase()) ||
          i.name.toLowerCase().includes(query.toLowerCase())
      )
    : allItems;

  const handleAnalyze = (symbol: string, assetType: 'crypto' | 'stock') => {
    navigate('/advisor', { state: { symbol, assetType } });
  };

  const handleAddCustom = () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    const isCrypto = sym.includes('/') || sym.includes('-') || sym.endsWith('USD') || sym.endsWith('USDT');
    const item: WatchItem = {
      symbol: sym,
      name: sym,
      category: isCrypto ? 'crypto' : 'stock',
      price: 0,
      change24h: 0,
      recommendation: 'hold',
      reason: 'Custom watchlist item — run Advisor for full analysis',
    };
    setCustomItems((prev) => [...prev, item]);
    setNewSymbol('');
    setShowAdd(false);
  };

  return (
    <Layout title="Watchlist">
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center"
        >
          <h2 className="text-xl font-bold text-text-primary">Assets to Watch</h2>
          <p className="mt-1 text-sm text-text-muted">
            Curated recommendations with trend signals. Click <strong>Analyze</strong> for a deep dive.
          </p>
        </motion.div>

        {/* Tabs + Search */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-1 rounded-md bg-bg-input border border-border-subtle p-0.5">
              <button
                onClick={() => setTab('crypto')}
                className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                  tab === 'crypto'
                    ? 'bg-bg-elevated text-accent-cyan'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                Crypto
              </button>
              <button
                onClick={() => setTab('stock')}
                className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                  tab === 'stock'
                    ? 'bg-bg-elevated text-accent-cyan'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                Stocks
              </button>
            </div>

            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-text-muted" />
                <input
                  type="text"
                  placeholder="Filter..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="w-40 rounded-md border border-border-subtle bg-bg-input py-1.5 pl-8 pr-3 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
                />
              </div>
              <button
                onClick={() => setShowAdd(!showAdd)}
                className="inline-flex items-center gap-1 rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
              >
                <Plus className="h-3.5 w-3.5" />
                Add
              </button>
            </div>
          </div>

          {/* Add custom */}
          {showAdd && (
            <div className="mt-3 flex items-center gap-2">
              <input
                type="text"
                placeholder="Symbol (e.g. BTC/USD or AAPL)"
                value={newSymbol}
                onChange={(e) => setNewSymbol(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddCustom()}
                className="flex-1 rounded-md border border-border-subtle bg-bg-input py-1.5 px-3 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
              <button
                onClick={handleAddCustom}
                className="rounded-md bg-accent-cyan px-3 py-1.5 text-xs font-semibold text-text-inverse hover:brightness-110 transition-all"
              >
                Add
              </button>
              <button
                onClick={() => { setShowAdd(false); setNewSymbol(''); }}
                className="rounded-md border border-border-subtle bg-bg-input px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-bg-elevated transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </motion.div>

        {/* Grid */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {filtered.map((item, idx) => (
            <motion.div
              key={item.symbol}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.03 }}
              className="rounded-[10px] border border-border-subtle bg-bg-surface p-4"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-text-primary">{item.symbol}</h3>
                    {recBadge(item.recommendation)}
                  </div>
                  <p className="text-xs text-text-muted">{item.name}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold text-text-primary">
                    ${item.price > 1 ? item.price.toLocaleString() : item.price.toFixed(4)}
                  </p>
                  <p
                    className={`flex items-center justify-end gap-1 text-xs ${
                      item.change24h >= 0 ? 'text-success-green' : 'text-danger-red'
                    }`}
                  >
                    {trendIcon(item.change24h)}
                    {item.change24h >= 0 ? '+' : ''}
                    {item.change24h.toFixed(2)}%
                  </p>
                </div>
              </div>

              <p className="mt-2 text-xs text-text-secondary leading-relaxed">{item.reason}</p>

              <div className="mt-3 flex items-center justify-end">
                <button
                  onClick={() => handleAnalyze(item.symbol, item.category)}
                  className="inline-flex items-center gap-1 rounded-md bg-accent-cyan/10 px-3 py-1.5 text-xs font-medium text-accent-cyan hover:bg-accent-cyan/20 transition-colors"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  Analyze
                  <ArrowRight className="h-3 w-3" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>

        {filtered.length === 0 && (
          <div className="flex h-48 flex-col items-center justify-center rounded-[10px] border border-border-subtle bg-bg-surface">
            <Search className="h-8 w-8 text-text-muted" />
            <p className="mt-2 text-sm text-text-muted">No assets match your filter</p>
          </div>
        )}
      </div>
    </Layout>
  );
}
