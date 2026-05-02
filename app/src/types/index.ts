export interface Portfolio {
  totalEquity: number;
  availableBalance: number;
  marginUsed: number;
  dailyPnl: number;
  dailyPnlPercent: number;
  totalPnl: number;
  totalPnlPercent: number;
}

export interface Position {
  id: string;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entryPrice: number;
  markPrice: number;
  pnl: number;
  pnlPercent: number;
  openedAt: string;
  strategy?: string;
}

export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit' | 'stop';
  size: number;
  price: number;
  status: 'filled' | 'pending' | 'cancelled';
  filledAt?: string;
}

export interface Trade {
  id: string;
  time: string;
  symbol: string;
  side: 'long' | 'short';
  price: number;
  size: number;
  pnl: number;
  strategy: string;
}

export interface Bot {
  id: string;
  name: string;
  strategy: string;
  pair: string;
  status: 'running' | 'stopped' | 'paused' | 'error';
  pnl: number;
  pnlPercent: number;
  uptime: string;
  uptimeSeconds: number;
  sparkline: number[];
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  category: string;
  winRate: number;
  avgReturn: number;
  sharpeRatio: number;
  maxDrawdown: number;
  tradesCount: number;
  params: StrategyParam[];
}

export interface StrategyParam {
  key: string;
  label: string;
  type: 'number' | 'string' | 'boolean' | 'select';
  default: string | number | boolean;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
}

export interface MarketTicker {
  symbol: string;
  price: number;
  change24h: number;
  change24hPercent: number;
  volume24h: number;
  high24h: number;
  low24h: number;
}

export interface BacktestResult {
  id: string;
  strategy: string;
  symbol: string;
  period: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  finalEquity: number;
  totalReturn: number;
  totalReturnPercent: number;
  sharpeRatio: number;
  maxDrawdown: number;
  maxDrawdownPercent: number;
  winRate: number;
  profitFactor: number;
  totalTrades: number;
  equityCurve: EquityCurvePoint[];
}

export interface EquityCurvePoint {
  date: string;
  equity: number;
}

export interface BotLog {
  id: string;
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'success';
  botId?: string;
  botName?: string;
  message: string;
}

export interface PerformanceMetrics {
  sharpeRatio: number;
  maxDrawdown: number;
  maxDrawdownPercent: number;
  profitFactor: number;
  tradesPerDay: number;
  winRate: number;
  avgWin: number;
  avgLoss: number;
  avgTradeDuration: number;
}

export interface AlertItem {
  id: string;
  type: 'bot' | 'trade' | 'system' | 'warning';
  title: string;
  message: string;
  timestamp: string;
  icon: string;
  severity: 'success' | 'info' | 'warning' | 'error';
}

export interface AssetAllocation {
  symbol: string;
  percentage: number;
  value: number;
  color: string;
}

export interface SentimentResult {
  articleId: string;
  symbol: string;
  compoundScore: number;
  positiveScore: number;
  negativeScore: number;
  neutralScore: number;
  confidence: number;
  model: string;
  impactAssessment: string;
  keyThemes: string[];
  analyzedAt: string;
}

export interface SymbolSentimentSummary {
  symbol: string;
  articleCount: number;
  avgCompound: number;
  sentimentLabel: string;
  latestHeadlines: string[];
  trending: boolean;
  updatedAt: string;
}

export interface TrendingSymbol {
  symbol: string;
  articleCount: number;
  avgCompound: number;
  sentimentLabel: string;
  latestHeadlines: string[];
  trending: boolean;
  updatedAt: string;
}

export interface NewsStatus {
  alpacaConfigured: boolean;
  llmProvider: string | null;
  llmConfigured: boolean;
  hybridMode: boolean;
  hybridThreshold: number;
  vaderAvailable: boolean;
  ollamaAvailable: boolean;
  timestamp: string;
}
