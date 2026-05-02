import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router'
import ErrorBoundary from './components/ErrorBoundary'
import { Loader2 } from 'lucide-react'

const Home = lazy(() => import('./pages/Home'))
const PaperTrading = lazy(() => import('./pages/PaperTrading'))
const Strategies = lazy(() => import('./pages/Strategies'))
const Backtest = lazy(() => import('./pages/Backtest'))
const Analytics = lazy(() => import('./pages/Analytics'))
const BotLab = lazy(() => import('./pages/BotLab'))
const Settings = lazy(() => import('./pages/Settings'))
const Advisor = lazy(() => import('./pages/Advisor'))
const About = lazy(() => import('./pages/About'))
const Watchlist = lazy(() => import('./pages/Watchlist'))

function PageLoader() {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-bg-base">
      <Loader2 className="h-8 w-8 animate-spin text-accent-cyan" />
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/paper" element={<PaperTrading />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/bots" element={<BotLab />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/advisor" element={<Advisor />} />
          <Route path="/about" element={<About />} />
          <Route path="/watchlist" element={<Watchlist />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  )
}
