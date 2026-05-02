# Paper Trading Bot Platform - AI Advisor Upgrade Plan

## New Features
1. **AI Advisor Engine** — Ask about ANY stock or crypto, get BUY/SELL/HOLD recommendation
2. **Price Prediction** — ML-driven price targets (buy zone, sell zone, stop loss)
3. **Professional Indicators** — VWAP, Ichimoku Cloud, Supertrend, Fibonacci, ADX/DMI, Pivot Points, Chaikin Money Flow, Williams %R, Stochastic RSI, Elder's Force Index
4. **Signal Synthesis** — Weighted ensemble of all indicators into a final verdict
5. **Risk Assessment** — Volatility analysis, position sizing recommendation

## Stage 1 — Backend Enhancement (Parallel)
**Agent: AI_Backend_Dev**
- Build `advisor/` module with:
  - `indicators.py` — 15+ professional TA indicators (pure pandas/numpy)
  - `predictor.py` — Price prediction using trend projection, ATR bands, Fibonacci extensions
  - `recommender.py` — Multi-factor recommendation engine (BUY/SELL/HOLD with confidence)
  - `analyzer.py` — Full symbol analysis orchestrator
- Add `/advisor` API routes to FastAPI
- Enhance existing strategies with new indicators

## Stage 2 — Frontend Enhancement (Parallel)
**Agent: AI_Frontend_Dev**
- Build `src/pages/Advisor.tsx` — AI-powered analysis page
- Features:
  - Ticker search bar (any stock/crypto symbol)
  - Big verdict card (BUY/SELL/HOLD with confidence %)
  - Predicted price targets (entry, take-profit, stop-loss)
  - Technical indicators grid (all 15+ with color-coded readings)
  - Signal strength radar/meter
  - Risk assessment card
  - "Pro Insight" summary text
  - Price chart with prediction overlay
- Update Navbar to include Advisor link
- Update App.tsx with new route

## Stage 3 — Integration & Deploy
- Merge frontend branch
- Build and deploy
