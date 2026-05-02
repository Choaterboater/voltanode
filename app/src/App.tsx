import { Routes, Route } from 'react-router'
import Home from './pages/Home'
import PaperTrading from './pages/PaperTrading'
import Strategies from './pages/Strategies'
import Backtest from './pages/Backtest'
import Analytics from './pages/Analytics'
import BotLab from './pages/BotLab'
import NewsSentiment from './pages/NewsSentiment'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/paper" element={<PaperTrading />} />
      <Route path="/strategies" element={<Strategies />} />
      <Route path="/backtest" element={<Backtest />} />
      <Route path="/analytics" element={<Analytics />} />
      <Route path="/bots" element={<BotLab />} />
      <Route path="/news" element={<NewsSentiment />} />
    </Routes>
  )
}
