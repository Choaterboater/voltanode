# Frontend Component Reference

## Shared Components

### `Layout`
**Location:** `src/components/Layout.tsx`
**Purpose:** Page wrapper providing the global sidebar navigation, sticky header, and footer.

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `children` | `ReactNode` | Yes | Page content |
| `title` | `string` | Yes | Header title |
| `rightContent` | `ReactNode` | No | Content rendered in the header right slot |

**Usage:**
```tsx
<Layout title="Dashboard" rightContent={<TimeRangeSelector />}>
  <HomeContent />
</Layout>
```

---

### `MetricCard`
**Location:** `src/components/MetricCard.tsx`
**Purpose:** Animated metric display card with optional delta indicator and child content (e.g., sparkline).

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `label` | `string` | — | Metric label |
| `value` | `string \| number` | — | Primary value |
| `delta` | `string \| number` | — | Secondary delta text |
| `deltaPositive` | `boolean` | `true` | Color delta green if true, red if false |
| `icon` | `ReactNode` | — | Icon element |
| `children` | `ReactNode` | — | Extra content (sparklines, charts) |
| `delay` | `number` | `0` | Animation delay (seconds) |

**Usage:**
```tsx
<MetricCard
  label="Today's P&L"
  value="+$2,847.33"
  delta="2.35%"
  deltaPositive={true}
  icon={<TrendingUp />}
  delay={0.08}
>
  <MiniSparkline data={sparklineData} color="#10B981" />
</MetricCard>
```

---

### `Badge`
**Location:** `src/components/Badge.tsx`
**Purpose:** Small status/label indicator with color-coded variants.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `'neutral' \| 'success' \| 'danger' \| 'warning' \| 'info' \| 'cyan'` | `'neutral'` | Color theme |
| `children` | `ReactNode` | Yes | Badge text/content |
| `className` | `string` | `''` | Additional Tailwind classes |

**Usage:**
```tsx
<Badge variant="success">3 running</Badge>
<Badge variant="danger">Short</Badge>
```

---

### `StatusDot`
**Location:** `src/components/StatusDot.tsx`
**Purpose:** Animated pulsing status indicator for bot/connection states.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `status` | `'running' \| 'stopped' \| 'paused' \| 'error'` | — | Status determines color and pulse |
| `className` | `string` | `''` | Additional classes |

**Usage:**
```tsx
<StatusDot status="running" />
<StatusDot status="paused" />
```

---

### `DataTable`
**Location:** `src/components/DataTable.tsx`
**Purpose:** Generic typed table with animated row entrance, empty state, and customizable columns.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `columns` | `DataTableColumn<T>[]` | Yes | Column definitions |
| `data` | `T[]` | Yes | Row data |
| `keyExtractor` | `(row: T) => string` | Yes | Unique key per row |
| `rowClassName` | `string` | `''` | Row class |
| `headerClassName` | `string` | `''` | Header row class |
| `cellClassName` | `string` | `''` | Cell class |
| `emptyMessage` | `string` | `'No data available'` | Empty state text |

**Column Definition:**
```tsx
interface DataTableColumn<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
}
```

**Usage:**
```tsx
<DataTable
  columns={[
    { key: 'symbol', header: 'Pair', render: (row) => <span>{row.symbol}</span> },
    { key: 'pnl', header: 'P&L', render: (row) => <span>${row.pnl}</span> },
  ]}
  data={trades}
  keyExtractor={(row) => row.id}
/>
```

---

### `Navbar`
**Location:** `src/components/Navbar.tsx`
**Purpose:** Responsive sidebar navigation with mobile hamburger toggle and active state highlighting.

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| *(none)* | — | — | Self-contained; reads `useLocation` |

**Navigation Items:**
- Dashboard (`/`)
- Paper Trading (`/paper`)
- Strategies (`/strategies`)
- Backtest (`/backtest`)
- Analytics (`/analytics`)
- Bot Lab (`/bots`)

---

### `Footer`
**Location:** `src/components/Footer.tsx`
**Purpose:** Simple footer with version info and trading mode label.

---

## Page Components

### `Home` (Dashboard)
**Location:** `src/pages/Home.tsx`
**Sub-components (inline):**
- `MiniSparkline` — Tiny Recharts `<LineChart>` for metric cards
- `DonutChart` — Small Recharts `<PieChart>` for win rate visualization

**Sections:**
1. Hero Metrics Row (4 `MetricCard`s)
2. Portfolio Overview (Equity curve `AreaChart` + Allocation `PieChart` + Key stats)
3. Active Bots (3 bot cards with sparklines)
4. Market Ticker Tape (animated marquee)
5. Recent Activity (Recent Trades `DataTable` + System Alerts)

---

### `PaperTrading`
**Location:** `src/pages/PaperTrading.tsx`
**Current State:** Placeholder page wrapped in `Layout`

---

### `Strategies`
**Location:** `src/pages/Strategies.tsx`
**Current State:** Placeholder page wrapped in `Layout`

---

### `Backtest`
**Location:** `src/pages/Backtest.tsx`
**Current State:** Placeholder page wrapped in `Layout`

---

### `Analytics`
**Location:** `src/pages/Analytics.tsx`
**Current State:** Placeholder page wrapped in `Layout`

---

### `BotLab`
**Location:** `src/pages/BotLab.tsx`
**Current State:** Placeholder page wrapped in `Layout`

---

## Hooks

### `useIsMobile`
**Location:** `src/hooks/use-mobile.ts`
**Purpose:** Detects viewport width below 768px using `matchMedia`.

**Returns:** `boolean` — `true` if mobile breakpoint is active.

**Cleanup:** Removes `change` event listener on unmount.

---

## Utilities

### `cn`
**Location:** `src/lib/utils.ts`
**Purpose:** Combines `clsx` and `tailwind-merge` for conditional class names.

**Usage:**
```tsx
<div className={cn('base-class', condition && 'conditional-class')} />
```
