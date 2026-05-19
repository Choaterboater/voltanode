import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Newspaper,
  Search,
  TrendingUp,
  Brain,
  Activity,
  Zap,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
} from 'lucide-react';
import Layout from '../components/Layout';
import MetricCard from '../components/MetricCard';
import Badge from '../components/Badge';
import DataTable from '../components/DataTable';
import { getNewsStatus, analyzeHeadline, getSymbolSentiment, getTrendingSymbols, getPriceMap } from '../lib/api';
import type { SentimentResult, TrendingSymbol, NewsStatus } from '../types';

export default function NewsSentiment() {
  const [status, setStatus] = useState<NewsStatus | null>(null);
  const [headline, setHeadline] = useState('');
  const [summary, setSummary] = useState('');
  const [symbolInput, setSymbolInput] = useState('');
  const [analyzeResults, setAnalyzeResults] = useState<SentimentResult[]>([]);
  const [analyzeLoading, setAnalyzeLoading] = useState(false);

  const [lookupSymbol, setLookupSymbol] = useState('');
  const [lookupResult, setLookupResult] = useState<{ symbol: string; scores: SentimentResult[]; summary: { avgCompound: number; articleCount: number; sentimentLabel: string } | null } | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);

  const [trending, setTrending] = useState<TrendingSymbol[]>([]);
  const [trendingLoading, setTrendingLoading] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Live prices for every symbol referenced on this page. Populated lazily
  // whenever analyzeResults / lookupResult / trending change. Map keyed by
  // upper-case symbol so the display lookups don't have to worry about case.
  const [priceMap, setPriceMap] = useState<Record<string, number>>({});

  const refreshPrices = useCallback(async (syms: string[]) => {
    const unique = Array.from(new Set(syms.map((s) => s.toUpperCase()).filter(Boolean)));
    if (unique.length === 0) return;
    try {
      const m = await getPriceMap(unique);
      setPriceMap((prev) => ({ ...prev, ...m }));
    } catch {
      // silent — prices are decoration, not load-bearing
    }
  }, []);

  // Renders "$215.30" or "—" so layouts stay consistent when a fetch fails
  // (e.g. yfinance hiccups on one symbol but not the others).
  const fmtPrice = (sym: string): string => {
    const p = priceMap[sym.toUpperCase()];
    if (typeof p !== 'number' || !isFinite(p)) return '—';
    if (p < 1) return `$${p.toFixed(4)}`;
    if (p < 100) return `$${p.toFixed(2)}`;
    return `$${p.toFixed(2)}`;
  };

  // Reusable lookup runner so trending cards (and the form) can both
  // trigger a sentiment fetch for a specific symbol without going through
  // a form submission event.
  const runLookup = async (sym: string) => {
    const s = sym.trim().toUpperCase();
    if (!s) return;
    setLookupSymbol(s);
    setLookupLoading(true);
    try {
      const res = await getSymbolSentiment(s);
      setLookupResult({
        symbol: res.symbol,
        scores: res.scores.map((r) => ({
          articleId: r.article_id,
          symbol: r.symbol,
          compoundScore: r.compound_score,
          positiveScore: r.positive_score,
          negativeScore: r.negative_score,
          neutralScore: r.neutral_score,
          confidence: r.confidence,
          model: r.model,
          impactAssessment: r.impact_assessment,
          keyThemes: r.key_themes,
          analyzedAt: r.analyzed_at,
        })),
        summary: res.summary
          ? {
              avgCompound: res.summary.avg_compound,
              articleCount: res.summary.article_count,
              sentimentLabel: res.summary.sentiment_label,
            }
          : null,
      });
    } catch {
      setLookupResult(null);
    } finally {
      setLookupLoading(false);
    }
  };

  const loadStatus = useCallback(async () => {
    try {
      const s = await getNewsStatus();
      setStatus({
        alpacaConfigured: s.alpaca_configured,
        llmProvider: s.llm_provider,
        llmConfigured: s.llm_configured,
        hybridMode: s.hybrid_mode,
        hybridThreshold: s.hybrid_threshold,
        vaderAvailable: s.vader_available,
        ollamaAvailable: s.ollama_available,
        timestamp: s.timestamp,
      });
    } catch {
      // silently fail
    }
  }, []);

  const loadTrending = useCallback(async () => {
    setTrendingLoading(true);
    try {
      const data = await getTrendingSymbols(24, 1);
      setTrending(
        data.map((t) => ({
          symbol: t.symbol,
          articleCount: t.article_count,
          avgCompound: t.avg_compound,
          sentimentLabel: t.sentiment_label,
          latestHeadlines: t.latest_headlines,
          trending: t.trending,
          updatedAt: t.updated_at,
        }))
      );
    } catch {
      setTrending([]);
    } finally {
      setTrendingLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadTrending();
    const interval = setInterval(loadStatus, 30000);
    return () => clearInterval(interval);
  }, [loadStatus, loadTrending]);

  // Whenever a result set lands, fetch prices for its symbols. Three
  // sources contribute (analyze, lookup, trending); each refresh merges
  // into the shared priceMap rather than overwriting.
  useEffect(() => {
    if (analyzeResults.length === 0) return;
    refreshPrices(analyzeResults.map((r) => r.symbol));
  }, [analyzeResults, refreshPrices]);

  useEffect(() => {
    if (!lookupResult) return;
    const syms = [lookupResult.symbol, ...lookupResult.scores.map((r) => r.symbol)];
    refreshPrices(syms);
  }, [lookupResult, refreshPrices]);

  useEffect(() => {
    if (trending.length === 0) return;
    refreshPrices(trending.map((t) => t.symbol));
  }, [trending, refreshPrices]);

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!headline.trim()) return;
    setAnalyzeLoading(true);
    try {
      const symbols = symbolInput.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
      const res = await analyzeHeadline(headline, summary, 'manual', symbols);
      setAnalyzeResults(
        res.results.map((r) => ({
          articleId: r.article_id,
          symbol: r.symbol,
          compoundScore: r.compound_score,
          positiveScore: r.positive_score,
          negativeScore: r.negative_score,
          neutralScore: r.neutral_score,
          confidence: r.confidence,
          model: r.model,
          impactAssessment: r.impact_assessment,
          keyThemes: r.key_themes,
          analyzedAt: r.analyzed_at,
        }))
      );
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setAnalyzeLoading(false);
    }
  };

  const handleLookup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!lookupSymbol.trim()) return;
    setLookupLoading(true);
    try {
      const res = await getSymbolSentiment(lookupSymbol.trim().toUpperCase());
      setLookupResult({
        symbol: res.symbol,
        scores: res.scores.map((r) => ({
          articleId: r.article_id,
          symbol: r.symbol,
          compoundScore: r.compound_score,
          positiveScore: r.positive_score,
          negativeScore: r.negative_score,
          neutralScore: r.neutral_score,
          confidence: r.confidence,
          model: r.model,
          impactAssessment: r.impact_assessment,
          keyThemes: r.key_themes,
          analyzedAt: r.analyzed_at,
        })),
        summary: res.summary
          ? {
              avgCompound: res.summary.avg_compound,
              articleCount: res.summary.article_count,
              sentimentLabel: res.summary.sentiment_label,
            }
          : null,
      });
    } catch {
      setLookupResult(null);
    } finally {
      setLookupLoading(false);
    }
  };

  const sentimentVariant = (compound: number): 'success' | 'danger' | 'neutral' => {
    if (compound > 0.15) return 'success';
    if (compound < -0.15) return 'danger';
    return 'neutral';
  };

  const sentimentLabel = (compound: number) => {
    if (compound > 0.15) return 'Bullish';
    if (compound < -0.15) return 'Bearish';
    return 'Neutral';
  };

  return (
    <Layout
      title="News & Sentiment"
      rightContent={
        <div className="flex items-center gap-2">
          {status?.ollamaAvailable ? (
            <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" />Ollama</Badge>
          ) : (
            <Badge variant="danger"><XCircle className="mr-1 h-3 w-3" />Ollama</Badge>
          )}
          {status?.vaderAvailable ? (
            <Badge variant="success">VADER</Badge>
          ) : (
            <Badge variant="warning"><AlertTriangle className="mr-1 h-3 w-3" />VADER</Badge>
          )}
        </div>
      }
    >
      {/* Compact status strip — config goes in a single thin row instead
          of 4 big tiles. Trader cares about news, not which LLM is wired. */}
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[10px] border border-border-subtle bg-bg-surface px-4 py-2 text-xs">
        <span className="flex items-center gap-1.5 text-text-muted">
          <Brain className="h-3.5 w-3.5" />
          <span>LLM</span>
          <span className="font-mono text-text-primary">{status?.llmProvider ?? '—'}</span>
          {status?.llmConfigured ? (
            <CheckCircle2 className="h-3 w-3 text-success-green" />
          ) : (
            <XCircle className="h-3 w-3 text-danger-red" />
          )}
        </span>
        <span className="flex items-center gap-1.5 text-text-muted">
          <Newspaper className="h-3.5 w-3.5" />
          <span>Alpaca news</span>
          {status?.alpacaConfigured ? (
            <CheckCircle2 className="h-3 w-3 text-success-green" />
          ) : (
            <XCircle className="h-3 w-3 text-danger-red" />
          )}
        </span>
        <span className="flex items-center gap-1.5 text-text-muted">
          <Activity className="h-3.5 w-3.5" />
          <span>Hybrid</span>
          <span className={`font-mono ${status?.hybridMode ? 'text-success-green' : 'text-text-muted'}`}>
            {status?.hybridMode ? 'ON' : 'OFF'}
          </span>
        </span>
        <span className="flex items-center gap-1.5 text-text-muted">
          <Zap className="h-3.5 w-3.5" />
          <span>Threshold</span>
          <span className="font-mono text-text-primary">{status?.hybridThreshold ?? 0.6}</span>
        </span>
      </div>

      {/* The page is now ordered: Symbol Lookup (primary) -> Trending
          (with clickable cards) -> collapsible Sentiment Analyzer. The
          Sentiment Analyzer is a developer-debugging tool, not what
          users come here for, so it's hidden by default. */}
      <div className="space-y-5">
        {/* Sentiment Analyzer (advanced/debug — collapsed by default) */}
        {advancedOpen ? null : (
          <button
            onClick={() => setAdvancedOpen(true)}
            className="w-full rounded-[10px] border border-dashed border-border-subtle bg-bg-surface px-4 py-2 text-left text-xs text-text-muted transition-colors hover:border-accent-cyan/30 hover:text-text-secondary"
          >
            <span className="inline-flex items-center gap-1.5">
              <Brain className="h-3.5 w-3.5" />
              Advanced: score a custom headline
            </span>
          </button>
        )}
        {advancedOpen && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h2 className="mb-4 flex items-center justify-between text-base font-semibold text-text-primary">
            <span className="flex items-center gap-2">
              <Brain className="h-5 w-5 text-accent-cyan" />
              Sentiment Analyzer
            </span>
            <button
              onClick={() => setAdvancedOpen(false)}
              className="text-xs font-normal text-text-muted hover:text-text-secondary"
            >
              hide
            </button>
          </h2>
          <form onSubmit={handleAnalyze} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs text-text-muted">Headline</label>
              <input
                type="text"
                value={headline}
                onChange={(e) => setHeadline(e.target.value)}
                placeholder="Apple reports record earnings..."
                className="w-full rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-muted">Summary (optional)</label>
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="Additional context..."
                rows={2}
                className="w-full rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-muted">Symbols (comma-separated)</label>
              <input
                type="text"
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                placeholder="AAPL, TSLA"
                className="w-full rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={analyzeLoading || !headline.trim()}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-cyan px-4 py-2 text-sm font-medium text-text-inverse transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {analyzeLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
              {analyzeLoading ? 'Analyzing...' : 'Analyze Sentiment'}
            </button>
          </form>

          {/* Results */}
          {analyzeResults.length > 0 && (
            <div className="mt-4 space-y-3">
              {analyzeResults.map((r) => (
                <div key={`${r.articleId}-${r.symbol}`} className="rounded-lg border border-border-subtle bg-bg-base p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium text-text-primary">{r.symbol}</span>
                      <span className="font-mono text-xs text-text-secondary tabular-nums">{fmtPrice(r.symbol)}</span>
                      <Badge variant={sentimentVariant(r.compoundScore)}>
                        {sentimentLabel(r.compoundScore)}
                      </Badge>
                      <Badge variant="cyan">{r.model}</Badge>
                    </div>
                    <span className="text-xs text-text-muted">
                      Impact: <span className="text-text-secondary">{r.impactAssessment}</span>
                    </span>
                  </div>
                  <div className="mb-2 grid grid-cols-4 gap-2">
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Compound</p>
                      <p className={`font-mono text-sm font-medium ${r.compoundScore > 0 ? 'text-success-green' : r.compoundScore < 0 ? 'text-danger-red' : 'text-text-secondary'}`}>
                        {r.compoundScore > 0 ? '+' : ''}{r.compoundScore.toFixed(3)}
                      </p>
                    </div>
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Confidence</p>
                      <p className="font-mono text-sm font-medium text-text-primary">{(r.confidence * 100).toFixed(0)}%</p>
                    </div>
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Pos</p>
                      <p className="font-mono text-sm font-medium text-success-green">{r.positiveScore.toFixed(2)}</p>
                    </div>
                    <div className="text-center">
                      <p className="text-xs text-text-muted">Neg</p>
                      <p className="font-mono text-sm font-medium text-danger-red">{r.negativeScore.toFixed(2)}</p>
                    </div>
                  </div>
                  {r.keyThemes.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {r.keyThemes.map((theme) => (
                        <span key={theme} className="rounded bg-bg-elevated px-2 py-0.5 text-xs text-text-secondary">
                          {theme}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </motion.div>
        )}

        {/* Symbol Lookup — PRIMARY action. Lookup a symbol, see its
            sentiment + headlines + per-article scores. Trending cards
            below also feed into this. */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.05 }}
          className="rounded-[10px] border border-border-subtle bg-bg-surface p-5"
        >
          <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-text-primary">
            <Search className="h-5 w-5 text-accent-cyan" />
            Symbol Sentiment Lookup
          </h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (lookupSymbol.trim()) runLookup(lookupSymbol);
            }}
            className="mb-3 flex gap-2"
          >
            <input
              type="text"
              value={lookupSymbol}
              onChange={(e) => setLookupSymbol(e.target.value.toUpperCase())}
              placeholder="Search by ticker — AAPL, NVDA, TSLA, BTCUSD..."
              className="flex-1 rounded-lg border border-border-subtle bg-bg-input px-3 py-2 text-sm font-mono text-text-primary placeholder:text-text-muted focus:border-accent-cyan focus:outline-none"
            />
            <button
              type="submit"
              disabled={lookupLoading || !lookupSymbol.trim()}
              className="flex items-center gap-2 rounded-lg bg-accent-cyan px-4 py-2 text-sm font-medium text-text-inverse transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {lookupLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              <span className="hidden sm:inline">Look up</span>
            </button>
          </form>
          {/* Quick-pick chips so a user can score any of the usual suspects
              with one click, without having to know to scroll down to the
              Trending grid first. */}
          <div className="mb-4 flex flex-wrap gap-1.5">
            <span className="text-[10px] uppercase tracking-wider text-text-muted">Quick</span>
            {['AAPL','NVDA','TSLA','MSFT','GOOGL','META','AMD','BTCUSD','ETHUSD'].map((sym) => (
              <button
                key={sym}
                onClick={() => runLookup(sym)}
                className="rounded-full border border-border-subtle bg-bg-input px-2.5 py-0.5 text-[11px] font-mono text-text-secondary transition-colors hover:border-accent-cyan/40 hover:text-accent-cyan"
              >
                {sym}
              </button>
            ))}
          </div>

          {lookupResult?.summary && (
            <div className="mb-4 rounded-lg border border-border-subtle bg-bg-base p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-text-primary">{lookupResult.symbol}</span>
                  <span className="font-mono text-xs text-text-secondary tabular-nums">{fmtPrice(lookupResult.symbol)}</span>
                </div>
                <Badge variant={sentimentVariant(lookupResult.summary.avgCompound)}>
                  {lookupResult.summary.sentimentLabel}
                </Badge>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <MetricCard label="Avg Compound" value={lookupResult.summary.avgCompound.toFixed(3)} />
                <MetricCard label="Articles" value={lookupResult.summary.articleCount} />
                <MetricCard label="Label" value={lookupResult.summary.sentimentLabel} />
              </div>
            </div>
          )}

          {lookupResult && lookupResult.scores.length > 0 && (
            <DataTable
              columns={[
                { key: 'symbol', header: 'Symbol', className: 'w-20' },
                { key: 'compoundScore', header: 'Compound', render: (r) => (
                  <span className={`font-mono ${r.compoundScore > 0 ? 'text-success-green' : r.compoundScore < 0 ? 'text-danger-red' : 'text-text-secondary'}`}>
                    {r.compoundScore.toFixed(3)}
                  </span>
                )},
                { key: 'confidence', header: 'Conf', render: (r) => <span className="font-mono">{(r.confidence * 100).toFixed(0)}%</span> },
                { key: 'model', header: 'Model', render: (r) => <Badge variant="cyan">{r.model}</Badge> },
                { key: 'impactAssessment', header: 'Impact', render: (r) => (
                  <Badge variant={r.impactAssessment === 'high' ? 'danger' : r.impactAssessment === 'medium' ? 'warning' : 'neutral'}>
                    {r.impactAssessment}
                  </Badge>
                )},
                { key: 'keyThemes', header: 'Themes', render: (r) => (
                  <div className="flex flex-wrap gap-1">
                    {r.keyThemes.slice(0, 3).map((t) => (
                      <span key={t} className="rounded bg-bg-elevated px-1.5 py-0.5 text-xs text-text-muted">{t}</span>
                    ))}
                  </div>
                )},
              ]}
              data={lookupResult.scores}
              keyExtractor={(r) => `${r.articleId}-${r.symbol}-${r.analyzedAt}`}
              emptyMessage="No sentiment scores found"
            />
          )}
        </motion.div>
      </div>

      {/* Trending Symbols */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.3 }}
        className="mt-6 rounded-[10px] border border-border-subtle bg-bg-surface p-5"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-semibold text-text-primary">
            <TrendingUp className="h-5 w-5 text-accent-cyan" />
            Trending by News Volume
          </h2>
          <button
            onClick={loadTrending}
            disabled={trendingLoading}
            className="flex items-center gap-1.5 rounded-lg border border-border-subtle bg-bg-input px-3 py-1.5 text-xs text-text-secondary transition-colors hover:text-text-primary"
          >
            {trendingLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <TrendingUp className="h-3 w-3" />}
            Refresh
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {trending.length === 0 && !trendingLoading && (
            <div className="col-span-full flex h-32 items-center justify-center rounded-lg border border-border-subtle bg-bg-base">
              <p className="text-sm text-text-muted">No trending symbols. Set Alpaca API keys to fetch news.</p>
            </div>
          )}
          {trending.map((t, i) => (
            <motion.button
              key={t.symbol}
              type="button"
              onClick={() => runLookup(t.symbol)}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: i * 0.05 }}
              className="text-left rounded-lg border border-border-subtle bg-bg-base p-4 transition-colors hover:border-accent-cyan/40 hover:bg-bg-elevated cursor-pointer"
              title={`Click to look up ${t.symbol} sentiment + headlines`}
            >
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-base font-semibold text-accent-cyan">{t.symbol}</span>
                  <span className="font-mono text-xs text-text-secondary tabular-nums">{fmtPrice(t.symbol)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={sentimentVariant(t.avgCompound)}>{t.sentimentLabel}</Badge>
                  <span className="text-xs text-text-muted">{t.articleCount} articles</span>
                </div>
              </div>
              <div className="mb-2 flex items-baseline gap-2">
                <span className={`font-mono text-lg font-medium ${t.avgCompound > 0 ? 'text-success-green' : t.avgCompound < 0 ? 'text-danger-red' : 'text-text-secondary'}`}>
                  {t.avgCompound > 0 ? '+' : ''}{t.avgCompound.toFixed(3)}
                </span>
                <span className="text-xs text-text-muted">avg sentiment</span>
              </div>
              {t.latestHeadlines.length > 0 ? (
                <div className="space-y-1">
                  {t.latestHeadlines.slice(0, 2).map((h, idx) => (
                    <p key={idx} className="truncate text-xs text-text-secondary">• {h}</p>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] italic text-text-muted">Click to load headlines →</p>
              )}
            </motion.button>
          ))}
        </div>
      </motion.div>
    </Layout>
  );
}
