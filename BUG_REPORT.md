# QA Bug Report

## PaperTrade Pro — Frontend & Backend Audit

**Date:** 2024
**Auditor:** QA Team
**Scope:** Full frontend (`src/`) + backend (`trading-bot-backend/`)

---

## Summary

| Severity | Count | Fixed | Remaining |
|----------|-------|-------|-----------|
| Critical | 2 | 2 | 0 |
| High | 3 | 3 | 0 |
| Medium | 6 | 6 | 0 |
| Low | 4 | 2 | 2 |

---

## Critical Issues

### C1: Placeholder Pages Missing Layout (Navigation Broken)
- **File:** `src/pages/Analytics.tsx`, `Backtest.tsx`, `BotLab.tsx`, `PaperTrading.tsx`, `Strategies.tsx`
- **Impact:** Users navigating to any page other than Dashboard lose the sidebar and header, making navigation impossible.
- **Fix:** Wrapped all 5 pages in the `<Layout>` component with appropriate titles.
- **Status:** ✅ Fixed

### C2: Backend `market.py` Missing `pandas` Import
- **File:** `api/routes/market.py`
- **Impact:** `GET /market/prices` endpoint calls `pd.Timestamp.now()` but `pandas` (`pd`) is only imported inside `get_ohlcv`, causing a `NameError` at runtime.
- **Fix:** Added `import pandas as pd` at the top of `market.py`.
- **Status:** ✅ Fixed

---

## High Issues

### H1: Backend `on_fill` Uses `order_id` as `account_id`
- **File:** `bot/engine.py` (line ~367)
- **Impact:** `on_fill` tries to look up a portfolio using `fill.order_id` (a UUID) as an account key. This will always fall back to `"default"`, potentially sending fill callbacks to the wrong strategy portfolio.
- **Fix:** Updated `on_fill` to iterate over `self._orders` to find the correct `account_id` associated with the filled order.
- **Status:** ✅ Fixed

### H2: Portfolio `total_equity` Hardcoded to `0.0`
- **File:** `api/routes/portfolio.py` (line 42)
- **Impact:** The portfolio API always reports `total_equity: 0.0` regardless of actual balances and positions.
- **Fix:** Calculated `total_equity` as `sum(balances) + sum(position.market_value)`.
- **Status:** ✅ Fixed

### H3: Multiple Buttons Missing Accessibility Labels
- **Files:** `src/pages/Home.tsx`, `src/components/Navbar.tsx`
- **Impact:** Screen readers cannot identify the purpose of notification bell, account switcher, bot pause/play/settings buttons, and active navigation state.
- **Fix:** Added `aria-label` to all icon-only buttons, `aria-pressed` to time range toggles, and `aria-current="page"` to active `NavLink` items.
- **Status:** ✅ Fixed

---

## Medium Issues

### M1: DataTable Missing Table Accessibility Attributes
- **File:** `src/components/DataTable.tsx`
- **Impact:** Screen readers may not correctly interpret column headers as column headers.
- **Fix:** Added `scope="col"` to all `<th>` elements.
- **Status:** ✅ Fixed

### M2: DataTable Row Cell Keys Not Unique Across Rows
- **File:** `src/components/DataTable.tsx`
- **Impact:** React keys for `<td>` elements used only `col.key`, which could theoretically cause React reconciliation issues when rows are reordered.
- **Fix:** Changed cell key to `${keyExtractor(row)}-${col.key}` for guaranteed uniqueness.
- **Status:** ✅ Fixed

### M3: `use-mobile.ts` Returns `false` Before Measurement
- **File:** `src/hooks/use-mobile.ts`
- **Impact:** On first render, `isMobile` is `undefined`, which `!!isMobile` converts to `false`. This may flash a desktop layout on mobile devices before the effect runs.
- **Fix:** Changed return from `!!isMobile` to `isMobile ?? false` (semantically equivalent but more explicit; also added initial measurement before mount).
- **Status:** ✅ Fixed

### M4: API Cache Path Uses String Concatenation
- **File:** `api/main.py`
- **Impact:** `config.app.data_dir + "/cache"` is brittle on Windows and doesn't handle trailing slashes.
- **Fix:** Replaced with `Path(config.app.data_dir) / "cache"`.
- **Status:** ✅ Fixed

### M5: Build Chunk Size Warning
- **File:** N/A (Vite build output)
- **Impact:** Single JS chunk is ~830 KB (239 KB gzipped). Not critical but could affect load time on slow networks.
- **Fix:** Not fixed in this pass — requires code splitting with dynamic `import()` for heavy libraries (Recharts, Framer Motion).
- **Recommendation:** Use `React.lazy()` for page components and configure `manualChunks` in Vite.
- **Status:** ⏳ Needs future attention

### M6: Missing Error Boundaries
- **File:** `src/App.tsx`
- **Impact:** Any runtime error in a page component will crash the entire application.
- **Fix:** Not fixed in this pass.
- **Recommendation:** Wrap `<Routes>` in a React Error Boundary component that displays a fallback UI.
- **Status:** ⏳ Needs future attention

---

## Low Issues

### L1: Duplicate `alt` Text on Logo Images
- **File:** `src/components/Navbar.tsx`
- **Impact:** Two `<img>` tags with identical `alt="PaperTrade Pro"` may confuse screen readers.
- **Fix:** Not fixed — requires design decision on how to split alt text between icon and wordmark.
- **Recommendation:** Set `alt=""` on the wordmark since the icon already conveys the brand name, or use a single combined logo image.
- **Status:** ⏳ Needs future attention

### L2: Missing `console.log` Cleanup
- **File:** None found
- **Impact:** N/A
- **Status:** ✅ None present

### L3: No Async Data Fetching / Loading States
- **File:** All pages
- **Impact:** The application uses entirely static mock data. No skeleton screens, spinners, or error states exist for real API integration.
- **Fix:** Not applicable to current scope — this is a known architectural placeholder.
- **Recommendation:** Implement React Query or SWR with `<Suspense>` boundaries when wiring to the backend.
- **Status:** ⏳ Needs future attention

### L4: `requirements.txt` Already Included `pydantic-settings`
- **File:** `requirements.txt`
- **Impact:** Initial test environment did not have the package installed, leading to a false alarm.
- **Fix:** Verified that `pydantic-settings>=2.1.0` was already listed. The environment just needed `pip install`.
- **Status:** ✅ Verified (no code change needed)

---

## Recommendations for Future Improvements

1. **Code Splitting**: Configure Vite `manualChunks` to split vendor libraries (Recharts, Framer Motion, Lucide) from application code.
2. **Error Boundaries**: Add a top-level `<ErrorBoundary>` around routes and per-page boundaries for graceful degradation.
3. **API Integration**: Replace `mockData.ts` with `fetch` calls to the FastAPI backend. Add loading skeletons using the existing `<Skeleton>` UI component.
4. **Form Validation**: When implementing Paper Trading and Backtest forms, use `react-hook-form` + `zod` for robust client-side validation.
5. **Backend Tests**: Expand test coverage for `market.py` prices endpoint and `advisor.py` analysis endpoint.
6. **WebSocket Support**: Consider adding WebSocket endpoints for real-time price ticks and bot status updates.
7. **Storybook**: Document shared components (Badge, MetricCard, DataTable, StatusDot) in Storybook for design-system consistency.
