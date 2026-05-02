import type {
  Portfolio,
  Position,
  Trade,
  Bot,
  Strategy,
  MarketTicker,
  BacktestResult,
  BotLog,
  PerformanceMetrics,
  AlertItem,
  AssetAllocation,
} from '@/types';

// Portfolio data
export const portfolio: Portfolio = {
  totalEquity: 124582.47,
  availableBalance: 45231.88,
  marginUsed: 79350.59,
  dailyPnl: 2847.33,
  dailyPnlPercent: 2.35,
  totalPnl: 24582.47,
  totalPnlPercent: 24.58,
};

// Asset allocation
export const assetAllocation: AssetAllocation[] = [
  { symbol: 'BTC', percentage: 35, value: 43603.86, color: '#06B6D4' },
  { symbol: 'ETH', percentage: 25, value: 31145.62, color: '#8B5CF6' },
  { symbol: 'SOL', percentage: 15, value: 18687.37, color: '#10B981' },
  { symbol: 'USD', percentage: 25, value: 31145.62, color: '#64748B' },
];

// Active positions
export const positions: Position[] = [
  { id: 'pos-1', symbol: 'BTC/USD', side: 'long', size: 0.35, entryPrice: 65432.5, markPrice: 67432.5, pnl: 1245.0, pnlPercent: 3.05, openedAt: '2024-01-15T10:30:00Z', strategy: 'Momentum' },
  { id: 'pos-2', symbol: 'ETH/USD', side: 'long', size: 2.5, entryPrice: 3120.0, markPrice: 3245.0, pnl: 312.5, pnlPercent: 4.01, openedAt: '2024-01-14T14:15:00Z', strategy: 'Grid' },
  { id: 'pos-3', symbol: 'SOL/USD', side: 'short', size: 50, entryPrice: 148.5, markPrice: 142.3, pnl: 310.0, pnlPercent: 4.17, openedAt: '2024-01-16T09:00:00Z', strategy: 'Mean Reversion' },
  { id: 'pos-4', symbol: 'BTC/USD', side: 'short', size: 0.2, entryPrice: 68100.0, markPrice: 67432.5, pnl: 133.5, pnlPercent: 1.96, openedAt: '2024-01-16T11:20:00Z', strategy: 'Breakout' },
  { id: 'pos-5', symbol: 'ETH/USD', side: 'short', size: 1.8, entryPrice: 3280.0, markPrice: 3245.0, pnl: 63.0, pnlPercent: 1.07, openedAt: '2024-01-15T16:45:00Z', strategy: 'MACD' },
  { id: 'pos-6', symbol: 'AVAX/USD', side: 'long', size: 80, entryPrice: 35.2, markPrice: 36.85, pnl: 132.0, pnlPercent: 4.69, openedAt: '2024-01-14T08:30:00Z', strategy: 'Arbitrage' },
  { id: 'pos-7', symbol: 'LINK/USD', side: 'long', size: 120, entryPrice: 14.8, markPrice: 15.35, pnl: 66.0, pnlPercent: 3.72, openedAt: '2024-01-15T13:10:00Z', strategy: 'ML Ensemble' },
];

// Market ticker data
export const marketTickers: MarketTicker[] = [
  { symbol: 'BTC', price: 67432.5, change24h: 823.4, change24hPercent: 1.24, volume24h: 28500000000, high24h: 68100.0, low24h: 66200.0 },
  { symbol: 'ETH', price: 3245.12, change24h: -45.3, change24hPercent: -1.38, volume24h: 12400000000, high24h: 3310.0, low24h: 3190.0 },
  { symbol: 'SOL', price: 142.35, change24h: 8.12, change24hPercent: 6.05, volume24h: 3200000000, high24h: 148.5, low24h: 133.0 },
  { symbol: 'AVAX', price: 36.85, change24h: 1.25, change24hPercent: 3.51, volume24h: 890000000, high24h: 37.5, low24h: 35.2 },
  { symbol: 'LINK', price: 15.35, change24h: -0.42, change24hPercent: -2.66, volume24h: 450000000, high24h: 15.85, low24h: 15.1 },
  { symbol: 'MATIC', price: 0.8754, change24h: 0.023, change24hPercent: 2.7, volume24h: 210000000, high24h: 0.91, low24h: 0.84 },
  { symbol: 'DOGE', price: 0.0892, change24h: 0.0015, change24hPercent: 1.71, volume24h: 1800000000, high24h: 0.091, low24h: 0.087 },
  { symbol: 'XRP', price: 0.6234, change24h: -0.012, change24hPercent: -1.89, volume24h: 1200000000, high24h: 0.64, low24h: 0.61 },
  { symbol: 'ADA', price: 0.5842, change24h: 0.018, change24hPercent: 3.18, volume24h: 560000000, high24h: 0.59, low24h: 0.56 },
  { symbol: 'DOT', price: 7.42, change24h: -0.18, change24hPercent: -2.37, volume24h: 340000000, high24h: 7.65, low24h: 7.35 },
];

// Active bots
export const bots: Bot[] = [
  {
    id: 'bot-1',
    name: 'Momentum Bot',
    strategy: 'Momentum',
    pair: 'BTC/USD',
    status: 'running',
    pnl: 1247.5,
    pnlPercent: 8.45,
    uptime: '2d 14h',
    uptimeSeconds: 223200,
    sparkline: [11800, 11950, 11820, 12050, 12100, 11980, 12200, 12150, 12300, 12450, 12320, 12500, 12480, 12600, 12550, 12700, 12650, 12800, 12750, 12900],
  },
  {
    id: 'bot-2',
    name: 'Grid Bot',
    strategy: 'Grid',
    pair: 'ETH/USD',
    status: 'running',
    pnl: 892.1,
    pnlPercent: 6.12,
    uptime: '5d 3h',
    uptimeSeconds: 442800,
    sparkline: [8200, 8350, 8300, 8450, 8400, 8550, 8500, 8600, 8550, 8700, 8650, 8800, 8750, 8900, 8850, 8920, 8880, 8900, 8910, 8921],
  },
  {
    id: 'bot-3',
    name: 'Mean Reversion',
    strategy: 'Mean Rev',
    pair: 'SOL/USD',
    status: 'paused',
    pnl: -234.2,
    pnlPercent: -3.18,
    uptime: 'Paused 3h ago',
    uptimeSeconds: 10800,
    sparkline: [4200, 4180, 4190, 4170, 4160, 4150, 4160, 4140, 4130, 4120, 4130, 4110, 4100, 4090, 4080, 4070, 4060, 4050, 4040, 4030],
  },
  {
    id: 'bot-4',
    name: 'Breakout Bot',
    strategy: 'Breakout',
    pair: 'AVAX/USD',
    status: 'running',
    pnl: 456.75,
    pnlPercent: 4.82,
    uptime: '1d 8h',
    uptimeSeconds: 115200,
    sparkline: [9000, 9100, 9050, 9200, 9150, 9300, 9250, 9400, 9350, 9450, 9400, 9500, 9450, 9550, 9500, 9560, 9520, 9560, 9540, 4567.5],
  },
  {
    id: 'bot-5',
    name: 'MACD Bot',
    strategy: 'MACD',
    pair: 'LINK/USD',
    status: 'stopped',
    pnl: -89.4,
    pnlPercent: -1.25,
    uptime: 'Stopped 12h ago',
    uptimeSeconds: 43200,
    sparkline: [7200, 7150, 7100, 7050, 7000, 6950, 6900, 6850, 6800, 6750, 6700, 6650, 6600, 6550, 6500, 6450, 6400, 6350, 6300, 6250],
  },
  {
    id: 'bot-6',
    name: 'Arbitrage Bot',
    strategy: 'Arbitrage',
    pair: 'ETH/USD',
    status: 'running',
    pnl: 342.8,
    pnlPercent: 2.91,
    uptime: '3d 6h',
    uptimeSeconds: 280800,
    sparkline: [11200, 11300, 11250, 11400, 11350, 11500, 11450, 11600, 11550, 11700, 11650, 11800, 11750, 11850, 11800, 11900, 11850, 11950, 11900, 3428],
  },
  {
    id: 'bot-7',
    name: 'ML Ensemble',
    strategy: 'ML Ensemble',
    pair: 'BTC/USD',
    status: 'running',
    pnl: 1876.25,
    pnlPercent: 12.34,
    uptime: '7d 2h',
    uptimeSeconds: 615600,
    sparkline: [15000, 15200, 15100, 15400, 15300, 15600, 15500, 15800, 15700, 16000, 15900, 16200, 16100, 16400, 16300, 16600, 16500, 16800, 16700, 17000],
  },
];

// Trade history
export const trades: Trade[] = [
  { id: 'trade-1', time: '14:32:05', symbol: 'BTC/USD', side: 'long', price: 67432.5, size: 0.15, pnl: 124.5, strategy: 'Momentum' },
  { id: 'trade-2', time: '14:28:12', symbol: 'ETH/USD', side: 'short', price: 3245.0, size: 1.2, pnl: -18.2, strategy: 'Grid' },
  { id: 'trade-3', time: '14:15:44', symbol: 'SOL/USD', side: 'long', price: 142.3, size: 10, pnl: 45.8, strategy: 'Mean Reversion' },
  { id: 'trade-4', time: '13:58:01', symbol: 'BTC/USD', side: 'short', price: 67500.0, size: 0.1, pnl: 6.8, strategy: 'Breakout' },
  { id: 'trade-5', time: '13:42:19', symbol: 'ETH/USD', side: 'long', price: 3220.0, size: 2.0, pnl: 50.0, strategy: 'MACD' },
  { id: 'trade-6', time: '13:25:33', symbol: 'AVAX/USD', side: 'long', price: 36.2, size: 50, pnl: 32.5, strategy: 'Arbitrage' },
  { id: 'trade-7', time: '13:10:55', symbol: 'LINK/USD', side: 'short', price: 15.55, size: 80, pnl: -16.0, strategy: 'ML Ensemble' },
  { id: 'trade-8', time: '12:58:41', symbol: 'BTC/USD', side: 'long', price: 67100.0, size: 0.2, pnl: 66.5, strategy: 'Momentum' },
  { id: 'trade-9', time: '12:44:22', symbol: 'SOL/USD', side: 'short', price: 145.0, size: 25, pnl: 67.5, strategy: 'Mean Reversion' },
  { id: 'trade-10', time: '12:30:18', symbol: 'ETH/USD', side: 'long', price: 3205.0, size: 1.5, pnl: 60.0, strategy: 'Grid' },
  { id: 'trade-11', time: '12:15:07', symbol: 'BTC/USD', side: 'short', price: 67800.0, size: 0.12, pnl: 51.0, strategy: 'Breakout' },
  { id: 'trade-12', time: '12:02:44', symbol: 'AVAX/USD', side: 'long', price: 35.5, size: 60, pnl: 81.0, strategy: 'Arbitrage' },
  { id: 'trade-13', time: '11:48:19', symbol: 'LINK/USD', side: 'long', price: 15.2, size: 100, pnl: 15.0, strategy: 'MACD' },
  { id: 'trade-14', time: '11:35:52', symbol: 'ETH/USD', side: 'short', price: 3255.0, size: 2.0, pnl: -20.0, strategy: 'ML Ensemble' },
  { id: 'trade-15', time: '11:22:38', symbol: 'BTC/USD', side: 'long', price: 66900.0, size: 0.18, pnl: 96.3, strategy: 'Momentum' },
  { id: 'trade-16', time: '11:10:15', symbol: 'SOL/USD', side: 'long', price: 140.0, size: 30, pnl: 69.0, strategy: 'Mean Reversion' },
  { id: 'trade-17', time: '10:58:03', symbol: 'BTC/USD', side: 'short', price: 67200.0, size: 0.1, pnl: 27.0, strategy: 'Grid' },
  { id: 'trade-18', time: '10:45:47', symbol: 'ETH/USD', side: 'long', price: 3180.0, size: 3.0, pnl: 195.0, strategy: 'Breakout' },
  { id: 'trade-19', time: '10:32:29', symbol: 'AVAX/USD', side: 'short', price: 37.0, size: 40, pnl: 46.0, strategy: 'Arbitrage' },
  { id: 'trade-20', time: '10:20:11', symbol: 'LINK/USD', side: 'long', price: 14.9, size: 150, pnl: 67.5, strategy: 'MACD' },
];

// Strategy library
export const strategies: Strategy[] = [
  {
    id: 'strat-1',
    name: 'Momentum',
    description: 'Trend-following strategy that enters positions in the direction of established price momentum. Uses EMA crossovers and a long-term trend filter for confirmation.',
    category: 'Trend',
    winRate: 62.4,
    avgReturn: 3.8,
    sharpeRatio: 1.72,
    maxDrawdown: -12.5,
    tradesCount: 348,
    params: [
      { key: 'fast_ema', label: 'Fast EMA', type: 'number', default: 12, min: 5, max: 30, step: 1 },
      { key: 'slow_ema', label: 'Slow EMA', type: 'number', default: 26, min: 15, max: 50, step: 1 },
      { key: 'trend_filter_ema', label: 'Trend Filter EMA', type: 'number', default: 200, min: 50, max: 300, step: 1 },
    ],
  },
  {
    id: 'strat-2',
    name: 'Mean Reversion',
    description: 'Counter-trend strategy that trades price deviations from the statistical mean. Generates buy signals when RSI is oversold and price touches the lower Bollinger Band.',
    category: 'Counter-Trend',
    winRate: 58.7,
    avgReturn: 2.4,
    sharpeRatio: 1.45,
    maxDrawdown: -9.8,
    tradesCount: 512,
    params: [
      { key: 'rsi_period', label: 'RSI Period', type: 'number', default: 14, min: 5, max: 30, step: 1 },
      { key: 'rsi_overbought', label: 'RSI Overbought', type: 'number', default: 70, min: 60, max: 90, step: 1 },
      { key: 'rsi_oversold', label: 'RSI Oversold', type: 'number', default: 30, min: 10, max: 40, step: 1 },
      { key: 'bb_period', label: 'BB Period', type: 'number', default: 20, min: 10, max: 50, step: 1 },
      { key: 'bb_std', label: 'BB Std Dev', type: 'number', default: 2, min: 1, max: 4, step: 0.1 },
    ],
  },
  {
    id: 'strat-3',
    name: 'Grid Trading',
    description: 'Systematic grid strategy that places buy orders below and sell orders above the current price at regular intervals. Profits from ranging markets without needing to predict direction.',
    category: 'Systematic',
    winRate: 71.2,
    avgReturn: 1.8,
    sharpeRatio: 1.88,
    maxDrawdown: -6.4,
    tradesCount: 1247,
    params: [
      { key: 'grid_levels', label: 'Grid Levels', type: 'number', default: 10, min: 4, max: 50, step: 1 },
      { key: 'grid_spacing_pct', label: 'Grid Spacing %', type: 'number', default: 1, min: 0.2, max: 5, step: 0.1 },
      { key: 'quantity_per_grid', label: 'Quantity per Grid', type: 'number', default: 0.01, min: 0.001, max: 1, step: 0.001 },
    ],
  },
  {
    id: 'strat-4',
    name: 'Breakout',
    description: 'Volatility expansion strategy that enters when price breaks above resistance or below support with volume confirmation. Captures the start of strong directional moves after consolidation.',
    category: 'Volatility',
    winRate: 54.3,
    avgReturn: 5.2,
    sharpeRatio: 1.35,
    maxDrawdown: -15.2,
    tradesCount: 186,
    params: [
      { key: 'lookback_period', label: 'Lookback Period', type: 'number', default: 20, min: 5, max: 60, step: 1 },
      { key: 'volume_multiplier', label: 'Volume Multiplier', type: 'number', default: 1.5, min: 1, max: 3, step: 0.1 },
      { key: 'breakout_threshold_pct', label: 'Breakout Threshold %', type: 'number', default: 0.5, min: 0.1, max: 2, step: 0.1 },
    ],
  },
  {
    id: 'strat-5',
    name: 'MACD',
    description: 'Classic MACD-based strategy using signal line crossovers. Buys when MACD crosses above signal with positive histogram. Sells on bearish cross with negative histogram.',
    category: 'Indicator',
    winRate: 59.8,
    avgReturn: 2.9,
    sharpeRatio: 1.52,
    maxDrawdown: -11.3,
    tradesCount: 423,
    params: [
      { key: 'fast', label: 'Fast EMA', type: 'number', default: 12, min: 5, max: 30, step: 1 },
      { key: 'slow', label: 'Slow EMA', type: 'number', default: 26, min: 15, max: 50, step: 1 },
      { key: 'signal', label: 'Signal EMA', type: 'number', default: 9, min: 5, max: 20, step: 1 },
    ],
  },
  {
    id: 'strat-6',
    name: 'Arbitrage',
    description: 'Cross-exchange arbitrage that monitors price discrepancies across markets. When spread exceeds minimum threshold after fees, buys on cheaper exchange and sells on expensive one.',
    category: 'Systematic',
    winRate: 85.4,
    avgReturn: 0.8,
    sharpeRatio: 2.34,
    maxDrawdown: -2.1,
    tradesCount: 2156,
    params: [
      { key: 'min_spread_pct', label: 'Min Spread %', type: 'number', default: 0.5, min: 0.1, max: 2, step: 0.1 },
      { key: 'fee_adjusted', label: 'Fee Adjusted', type: 'boolean', default: true },
    ],
  },
  {
    id: 'strat-7',
    name: 'ML Ensemble',
    description: 'Machine learning ensemble combining RSI, MACD, EMA cross, Bollinger position, and volume trend into a weighted composite score. Optional Random Forest enhancement with sklearn.',
    category: 'AI/ML',
    winRate: 64.1,
    avgReturn: 4.2,
    sharpeRatio: 1.95,
    maxDrawdown: -8.7,
    tradesCount: 267,
    params: [
      { key: 'buy_threshold', label: 'Buy Threshold', type: 'number', default: 0.6, min: 0.3, max: 0.9, step: 0.05 },
      { key: 'sell_threshold', label: 'Sell Threshold', type: 'number', default: -0.6, min: -0.9, max: -0.3, step: 0.05 },
      { key: 'use_ml', label: 'Use ML Enhancement', type: 'boolean', default: false },
    ],
  },
];

// Equity curve data (30 days)
export const equityCurveData = Array.from({ length: 30 }, (_, i) => {
  const base = 100000;
  const growth = 24582.47;
  const noise = Math.sin(i * 0.5) * 2000 + Math.random() * 1000 - 500;
  const trend = (i / 29) * growth;
  return {
    date: new Date(Date.now() - (29 - i) * 24 * 60 * 60 * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    equity: Math.round((base + trend + noise) * 100) / 100,
  };
});

// Backtest results
export const backtestResults: BacktestResult[] = [
  {
    id: 'bt-1',
    strategy: 'Momentum',
    symbol: 'BTC/USD',
    period: '30D',
    startDate: '2024-01-01',
    endDate: '2024-01-30',
    initialCapital: 10000,
    finalEquity: 10845,
    totalReturn: 845,
    totalReturnPercent: 8.45,
    sharpeRatio: 1.72,
    maxDrawdown: -1250,
    maxDrawdownPercent: -12.5,
    winRate: 62.4,
    profitFactor: 2.14,
    totalTrades: 28,
    equityCurve: Array.from({ length: 30 }, (_, i) => ({
      date: `Day ${i + 1}`,
      equity: 10000 + i * 28.17 + Math.sin(i) * 200,
    })),
  },
  {
    id: 'bt-2',
    strategy: 'Grid',
    symbol: 'ETH/USD',
    period: '30D',
    startDate: '2024-01-01',
    endDate: '2024-01-30',
    initialCapital: 5000,
    finalEquity: 5306,
    totalReturn: 306,
    totalReturnPercent: 6.12,
    sharpeRatio: 1.88,
    maxDrawdown: -320,
    maxDrawdownPercent: -6.4,
    winRate: 71.2,
    profitFactor: 2.83,
    totalTrades: 42,
    equityCurve: Array.from({ length: 30 }, (_, i) => ({
      date: `Day ${i + 1}`,
      equity: 5000 + i * 10.2 + Math.cos(i) * 50,
    })),
  },
];

// Bot logs
export const botLogs: BotLog[] = [
  { id: 'log-1', timestamp: '14:30:05', level: 'success', botId: 'bot-1', botName: 'Momentum Bot', message: 'Bot started on BTC/USD' },
  { id: 'log-2', timestamp: '14:28:12', level: 'info', botId: 'bot-2', botName: 'Grid Bot', message: 'Take profit triggered at $3,280' },
  { id: 'log-3', timestamp: '13:45:02', level: 'warn', message: 'BTC volatility spike detected (14% in 1h)' },
  { id: 'log-4', timestamp: '12:18:33', level: 'info', botId: 'bot-3', botName: 'Mean Reversion', message: 'Position closed, P&L -$45.20' },
  { id: 'log-5', timestamp: '11:52:17', level: 'error', botId: 'bot-5', botName: 'MACD Bot', message: 'API connection timeout, bot stopped' },
  { id: 'log-6', timestamp: '11:30:00', level: 'success', botId: 'bot-4', botName: 'Breakout Bot', message: 'Entered long position at $36.20' },
  { id: 'log-7', timestamp: '10:15:22', level: 'info', botId: 'bot-6', botName: 'Arbitrage Bot', message: 'Arbitrage opportunity detected: 0.18% spread' },
  { id: 'log-8', timestamp: '09:45:10', level: 'info', botId: 'bot-7', botName: 'ML Ensemble', message: 'Model retrained with latest 24h data' },
];

// Performance metrics
export const performanceMetrics: PerformanceMetrics = {
  sharpeRatio: 1.84,
  maxDrawdown: -8123.5,
  maxDrawdownPercent: -8.2,
  profitFactor: 2.14,
  tradesPerDay: 12.3,
  winRate: 68.4,
  avgWin: 342.5,
  avgLoss: -128.3,
  avgTradeDuration: 245,
};

// Alerts / notifications
export const alerts: AlertItem[] = [
  {
    id: 'alert-1',
    type: 'bot',
    title: 'Bot Started',
    message: 'Momentum Bot started on BTC/USD',
    timestamp: '14:30:05',
    icon: 'Play',
    severity: 'success',
  },
  {
    id: 'alert-2',
    type: 'trade',
    title: 'Take Profit Hit',
    message: 'Grid Bot ETH/USD take profit triggered at $3,280',
    timestamp: '14:22:18',
    icon: 'Target',
    severity: 'info',
  },
  {
    id: 'alert-3',
    type: 'warning',
    title: 'High Volatility Warning',
    message: 'BTC volatility spike detected (14% in 1h)',
    timestamp: '13:45:02',
    icon: 'AlertTriangle',
    severity: 'warning',
  },
  {
    id: 'alert-4',
    type: 'trade',
    title: 'Position Closed',
    message: 'Mean Reversion SOL/USD position closed, P&L -$45.20',
    timestamp: '12:18:33',
    icon: 'CheckCircle',
    severity: 'success',
  },
];

// Sparkline data for metric cards
export const balanceSparkline = [121000, 121500, 121200, 122000, 122500, 122300, 123000, 123200, 123500, 124000, 123800, 124200, 124000, 124500, 124300, 124800, 124600, 125000, 124900, 125200, 125000, 125400, 125300, 125600, 125500, 125800, 125700, 126000, 125900, 124582.47];
export const pnlSparkline = [1200, 1350, 1100, 1600, 1800, 1500, 1900, 1700, 2000, 2200, 1950, 2100, 1900, 2300, 2100, 2400, 2200, 2500, 2300, 2600, 2400, 2700, 2500, 2800, 2600, 2900, 2700, 3000, 2800, 2847.33];
