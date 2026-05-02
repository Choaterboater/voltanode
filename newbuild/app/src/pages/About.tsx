import Layout from '@/components/Layout';
import { motion } from 'framer-motion';
import { Zap, Shield, BarChart3, Bot, Target, TrendingUp } from 'lucide-react';

const features = [
  {
    icon: <Zap className="h-5 w-5 text-accent-cyan" />,
    title: 'AI-Powered Analysis',
    description: 'Get professional-grade BUY/SELL/HOLD recommendations powered by 16+ technical indicators and ensemble scoring.',
  },
  {
    icon: <Bot className="h-5 w-5 text-accent-cyan" />,
    title: 'Algorithmic Bots',
    description: 'Deploy automated trading strategies including momentum, mean reversion, grid trading, and breakout detection.',
  },
  {
    icon: <BarChart3 className="h-5 w-5 text-accent-cyan" />,
    title: 'Backtest Engine',
    description: 'Test your strategies against historical market data before risking a single dollar.',
  },
  {
    icon: <Target className="h-5 w-5 text-accent-cyan" />,
    title: 'Price Predictions',
    description: 'ML-driven price targets using ATR channels, Fibonacci extensions, pivot points, and Ichimoku Cloud analysis.',
  },
  {
    icon: <Shield className="h-5 w-5 text-accent-cyan" />,
    title: 'Risk Management',
    description: 'Built-in kill switches, position sizing, stop-losses, and safety limits to protect your portfolio.',
  },
  {
    icon: <TrendingUp className="h-5 w-5 text-accent-cyan" />,
    title: 'Multi-Asset Support',
    description: 'Trade crypto via CoinGecko and stocks via Yahoo Finance — all from a single unified dashboard.',
  },
];

export default function About() {
  return (
    <Layout title="About">
      <div className="mx-auto max-w-3xl space-y-8">
        {/* Hero */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center"
        >
          <h1 className="text-3xl font-extrabold tracking-tight text-text-primary">
            VoltaNode
          </h1>
          <p className="mt-2 text-sm text-accent-cyan font-medium">
            Trade at the speed of thought
          </p>
          <p className="mt-4 text-sm leading-relaxed text-text-secondary">
            VoltaNode is an AI-powered paper trading platform built by{' '}
            <a
              href="https://choatelabs.app/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-cyan hover:underline"
            >
              Choate Labs
            </a>
            . Our mission is to democratize algorithmic trading by giving everyone access to institutional-grade tools — with zero real-money risk.
          </p>
        </motion.div>

        {/* Features Grid */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <h2 className="mb-4 text-base font-semibold text-text-primary">What You Can Do</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {features.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15 + i * 0.05 }}
                className="rounded-[10px] border border-border-subtle bg-bg-surface p-4 hover:border-accent-cyan/20 transition-colors"
              >
                <div className="flex items-center gap-2">
                  {f.icon}
                  <h3 className="text-sm font-semibold text-text-primary">{f.title}</h3>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-text-muted">{f.description}</p>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Parent Company */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h2 className="text-base font-semibold text-text-primary">Parent Company</h2>
          <div className="mt-3 flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-cyan/10">
              <Zap className="h-5 w-5 text-accent-cyan" />
            </div>
            <div>
              <p className="text-sm font-semibold text-text-primary">Choate Labs</p>
              <p className="mt-1 text-xs leading-relaxed text-text-secondary">
                Precision software for modern markets. Choate Labs builds the future of algorithmic trading and quantitative finance tools. We believe powerful technology should be accessible to every trader — not just institutions.
              </p>
              <a
                href="https://choatelabs.app/"
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-block text-xs text-accent-cyan hover:underline"
              >
                Visit choatelabs.app →
              </a>
            </div>
          </div>
        </motion.div>

        {/* Disclaimer */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
          className="rounded-lg border border-warning-amber/20 bg-warning-amber/5 p-3"
        >
          <p className="text-xs leading-relaxed text-warning-amber">
            <strong>Disclaimer:</strong> VoltaNode is a paper trading platform. No real money is traded. AI recommendations and price predictions are generated from technical analysis and do not constitute financial advice. Always do your own research before making investment decisions.
          </p>
        </motion.div>
      </div>
    </Layout>
  );
}
