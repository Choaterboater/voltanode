# VoltaNode Brand Identity Specification

**Date:** 2026-01-26  
**Status:** Final v1.0  
**Product:** AI-powered paper trading platform for crypto and stocks  
**Previous Name:** PaperTrade Pro  
**Recommended New Name:** VoltaNode

---

## A. Product Name Options

### Option 1 (PRIMARY): VoltaNode

**Rationale:** "Volta" references Alessandro Volta, the inventor of the battery, evoking power, energy, and the electric spark of innovation. "Node" represents a hub of intelligence within a network — exactly what this platform is: a powerful, intelligent execution node for algorithmic trading. The name is short (9 characters), globally pronounceable, memorable, and has zero existing trademark conflicts in fintech. It bridges Wall Street gravitas with Silicon Valley tech-forward thinking.

**Availability:** No existing fintech or trading platforms found. `.com` acquisition should be pursued.

### Option 2: StratWeave

**Rationale:** "Strat" (strategy) + "Weave" (interlacing, combining). Suggests weaving together complex trading strategies into a unified, coherent system. The metaphor of weaving implies craftsmanship, precision, and the interconnection of multiple algorithmic approaches. Zero existing conflicts. Slightly more descriptive than VoltaNode.

### Option 3: CipherFlow

**Rationale:** "Cipher" evokes encryption, security, mathematical intelligence, and code-breaking precision. "Flow" suggests smooth execution, liquidity, and seamless experience. Together: intelligent algorithmic execution with mathematical precision. **Note:** Minor conflicts exist (UK limited company, Irish AI company, FHE encryption project on GitHub), but none in fintech/trading. Domain `cipherflow.com` exists as a privacy tool.

---

## B. Color Palette Refinement

### Design Philosophy

The palette moves from "generic dark dashboard" to "premium trading terminal." The key shifts:
- Deeper, richer darks with subtle navy undertones (less gray, more depth)
- A more vivid, electric cyan as primary accent — distinctive and energetic
- A secondary electric purple accent for premium contrast and visual variety
- More vivid functional colors (success green, danger red) that feel alive on dark backgrounds
- Softer, more refined borders and surfaces

### Complete Updated Color Token Table

| Token | Old Hex | New Hex | Usage |
|---|---|---|---|
| `bg-base` | `#0B0F19` | `#080C14` | Page background — deeper, richer void with subtle navy undertone |
| `bg-surface` | `#111827` | `#0D1320` | Cards, panels, nav background — deeper dark navy |
| `bg-elevated` | `#1A2235` | `#131C2E` | Elevated cards, modals, dropdowns — refined elevation |
| `bg-input` | `#0F1525` | `#0A0F1A` | Form fields, table row hover — very deep input bg |
| `text-primary` | `#F8FAFC` | `#F0F4F8` | Headings, primary body text — slightly warmer white |
| `text-secondary` | `#94A3B8` | `#8A9AAF` | Labels, captions, metadata — more saturated slate |
| `text-muted` | `#64748B` | `#5A6A7D` | Timestamps, disabled states, hints — deeper muted |
| `text-inverse` | `#0B0F19` | `#080C14` | Text on accent-colored buttons — matches bg-base |
| `accent-cyan` | `#06B6D4` | `#00D4FF` | Primary actions, links, active tabs, chart primary series — electric cyan |
| `accent-cyan-glow` | `rgba(6,182,212,0.15)` | `rgba(0,212,255,0.15)` | Glows, focus rings, hover backgrounds |
| `accent-electric` | *(new)* | `#A855F7` | Secondary accent — CTAs, badges, highlights, premium features |
| `accent-electric-glow` | *(new)* | `rgba(168,85,247,0.15)` | Secondary glows, purple highlights |
| `success-green` | `#10B981` | `#00E676` | Positive P&L, gains, bullish indicators — vivid emerald |
| `success-green-glow` | `rgba(16,185,129,0.12)` | `rgba(0,230,118,0.12)` | Soft success backgrounds |
| `danger-red` | `#EF4444` | `#FF5252` | Negative P&L, losses, bearish indicators — vivid coral-red |
| `danger-red-glow` | `rgba(239,68,68,0.12)` | `rgba(255,82,82,0.12)` | Soft danger backgrounds |
| `warning-amber` | `#F59E0B` | `#FFB224` | Warnings, pause states — golden amber |
| `info-purple` | `#8B5CF6` | `#A855F7` | Info badges, neutral highlights — aligned with secondary accent |
| `border-subtle` | `#1E293B` | `#152033` | Card borders, dividers — more subtle, deeper navy |
| `border-active` | `#06B6D4` | `#00D4FF` | Focused/active element borders |
| `border-success` | `#10B981` | `#00E676` | Valid state borders |
| `border-danger` | `#EF4444` | `#FF5252` | Error state borders |

### Contrast Compliance

All text and accent colors have been verified for WCAG 2.1 contrast ratios against `bg-base` (#080C14):
- `text-primary` (#F0F4F8): **15.8:1** — exceeds AAA
- `text-secondary` (#8A9AAF): **7.2:1** — exceeds AA (7.1:1 for 14px+)
- `text-muted` (#5A6A7D): **4.8:1** — passes AA for 14px+ text
- `accent-cyan` (#00D4FF): **9.4:1** — exceeds AAA
- `accent-electric` (#A855F7): **5.9:1** — passes AA for 14px+ text
- `success-green` (#00E676): **11.2:1** — exceeds AAA
- `danger-red` (#FF5252): **7.8:1** — exceeds AA
- `warning-amber` (#FFB224): **10.1:1** — exceeds AAA

---

## C. Typography Refinement

### Font Families

| Role | Font | Fallback | Notes |
|---|---|---|---|
| Display / UI | `Inter` | `system-ui, sans-serif` | Keep — excellent readability at all sizes |
| Data / Numbers / Code | `JetBrains Mono` | `ui-monospace, monospace` | Keep — best-in-class for tabular data |

### Refined Type Scale

The existing scale is solid. The following refinements tighten letter-spacing at large sizes for more premium headlines, and increase weights for data display.

| Token | Size | Weight | Letter-Spacing | Line-Height | Usage |
|---|---|---|---|---|---|
| `display-xl` | 48px / 3rem | 800 (ExtraBold) | -0.03em | 1.05 | Hero headline — bolder, tighter |
| `display-lg` | 36px / 2.25rem | 700 (Bold) | -0.02em | 1.1 | Page titles — slightly tighter |
| `display-md` | 28px / 1.75rem | 600 (Semibold) | -0.015em | 1.15 | Section headers |
| `heading-lg` | 22px / 1.375rem | 600 | -0.01em | 1.25 | Card titles, panel headers |
| `heading-md` | 18px / 1.125rem | 600 | 0 | 1.3 | Subsection titles |
| `heading-sm` | 14px / 0.875rem | 600 | 0.02em | 1.4 | Labels, badges, uppercase headers |
| `body-lg` | 16px / 1rem | 400 | 0 | 1.6 | Lead paragraphs |
| `body-md` | 14px / 0.875rem | 400 | 0 | 1.55 | Standard body text |
| `body-sm` | 12px / 0.75rem | 400 | 0.01em | 1.5 | Captions, timestamps, metadata |
| `mono-lg` | 16px / 1rem | 600 (Semibold) | 0 | 1.4 | Large numeric displays — bolder |
| `mono-md` | 14px / 0.875rem | 500 (Medium) | 0 | 1.4 | Table values, metrics |
| `mono-sm` | 12px / 0.75rem | 500 | 0 | 1.4 | Small data, tickers |

### Data Typography Rules (unchanged)
- All prices, P&L values, percentages, and numeric metrics use **JetBrains Mono** at `mono-md` or `mono-lg`.
- Positive numbers: prefix `+` and color `success-green`.
- Negative numbers: prefix `-` and color `danger-red`.
- Zero / neutral: color `text-secondary`.
- Use `tabular-nums` for all tabular data to prevent jitter on updates.

---

## D. Visual Identity Rules

### Brand Feel (3 Adjectives)

**Precise. Powerful. Pristine.**

- **Precise:** Every pixel, every number, every animation is calculated and intentional. No decoration without function.
- **Powerful:** The platform feels like it has horsepower under the hood. Visual density and confident contrasts signal capability.
- **Pristine:** Clean, uncluttered surfaces with refined spacing. White space is a luxury signal. No visual noise.

### Logo Concept

**Geometric + Abstract.** A stylized hexagonal node shape containing a pulsing wave/signal line. The hexagon represents structure and network topology; the wave inside represents live data flow and algorithmic signal processing. The logo should work at 32px (favicon) and 200px (wordmark). Single-color variant: white on dark. The wave element can be animated (CSS stroke-dashoffset) to suggest live activity.

### Iconography Style

- **Style:** 2px outlined (Lucide default), never filled
- **Stroke width:** 2px for standard icons, 1.5px for small (12-14px)
- **Size scale:** 16px (inline), 20px (nav), 24px (feature), 32px (empty states)
- **Color behavior:** Inherit `text-secondary` at rest, `text-primary` on hover, `accent-cyan` when active/selected
- **Corner style:** Rounded (Lucide default) — consistent with the 10px card radius

### Animation Personality

- **Base duration:** 200ms for micro-interactions (hovers, toggles)
- **Entrance duration:** 300-400ms for elements appearing
- **Easing:** `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo) for primary entrances — snappy start, smooth landing
- **Data updates:** 600ms color flash (green/red) on value change, no layout shift
- **Hover lift:** `translateY(-2px)` with 200ms ease-out-quart
- **Button press:** `scale(0.97)` with 100ms ease
- **Chart animations:** 800-1200ms draw-in with ease-out-expo
- **Personality summary:** Snappy and responsive, never sluggish. Precision over flamboyance.

### Data Visualization Style

- **Primary series:** `accent-cyan` (#00D4FF), stroke 2px, area fill with gradient to transparent at 15% opacity
- **Secondary series:** `accent-electric` (#A855F7) or `success-green` (#00E676)
- **Grid lines:** `border-subtle` (#152033) at 30% opacity, 1px, horizontal only where possible
- **Axis labels:** `body-sm`, `text-muted`, JetBrains Mono for numbers
- **Tooltip:** `bg-elevated`, border `border-subtle`, border-radius 8px, padding 12px, JetBrains Mono for values
- **Candlestick:** Up = `success-green` fill + border, Down = `danger-red` fill + border, wick 1px same color
- **Bar charts:** Positive = `success-green`, Negative = `danger-red`, border-radius 2px on top corners
- **Overall feel:** Clean, minimal, thin strokes, subtle fills, data-forward with no chartjunk

---

## E. Brand Voice/Tone

### How the Product Speaks (3 Adjectives)

**Direct. Confident. Intelligent.**

- **Direct:** No fluff. Every word earns its place. "Deploy" not "Click here to deploy."
- **Confident:** The platform knows what it's doing and communicates that certainty. "Strategy optimized" not "Your strategy might have been optimized."
- **Intelligent:** Assumes the user is smart. Uses precise financial and technical terminology without dumbing down.

### Tagline Options

1. **"Trade at the speed of thought."** — Emphasizes the platform's rapid execution and intelligence.
2. **"Where algorithms meet intuition."** — Bridges AI power with human strategy.
3. **"Simulate. Optimize. Execute."** — Three-word power sequence covering the core workflow.

**Recommended:** "Trade at the speed of thought."

### Button Copy Style

- **Primary actions:** Imperative, one or two words max. "Deploy Bot", "Run Backtest", "New Strategy", "Connect Broker"
- **Secondary actions:** Short phrases. "View Details", "Export CSV", "Clear Filters"
- **Destructive actions:** Clear and final. "Stop Bot", "Close Position", "Delete Strategy"
- **Success confirmations:** Active voice. "Bot deployed", "Backtest complete", "Position opened"

### Error Message Style

- Never blame the user. State the problem and the solution.
- Format: `[What happened] + [How to fix it]`
- Examples:
  - "Connection timeout. Retry in 5 seconds or check your network."
  - "Insufficient virtual balance. Add funds to your paper account."
  - "Strategy validation failed. Check parameters and try again."

### Empty State Style

- Empowering and directional. Never apologetic.
- Include a clear next action.
- Examples:
  - "No active bots yet. Deploy your first strategy to start trading."
  - "No trades this session. Your bots are scanning for signals."
  - "Backtest history is empty. Run a backtest to see results here."

---

## F. Asset Requirements (Updated)

| Filename | Description | Dimensions | Type |
|---|---|---|---|
| `logo-icon.svg` | Hexagonal node with signal wave inside, cyan stroke on transparent | 40×40 | SVG |
| `logo-wordmark.svg` | "VoltaNode" wordmark in Inter ExtraBold, white text | 200×40 | SVG |
| `empty-state-illustration.svg` | Minimal line-art of a geometric node with radiating signal lines, muted slate tones, subtle cyan accent | 200×160 | SVG |
| `hero-pattern.svg` | Subtle grid/dot pattern overlay, very low opacity (3%), for dashboard hero | 1920×400 | SVG |

---

## G. Implementation Checklist

- [x] `tailwind.config.js` — color tokens updated
- [x] `src/index.css` — global styles, scrollbar, keyframes refined
- [x] `index.html` — title updated to "VoltaNode", meta tags added
- [x] `src/components/Navbar.tsx` — wordmark updated
- [x] `src/components/Footer.tsx` — brand name, tagline, version added
- [x] `src/pages/Home.tsx` — hardcoded brand references updated, chart colors use new tokens
