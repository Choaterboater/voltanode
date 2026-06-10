/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 2026-06-09 redesign: same token names, lifted values. Deeper base,
        // clearly-separated surfaces, brighter accents tuned for dark bg,
        // and borders that are actually visible. Pages keep their classes.
        'bg-base': '#070B14',
        'bg-surface': '#0D1424',
        'bg-elevated': '#16203A',
        'bg-input': '#0A111F',
        'text-primary': '#F2F6FC',
        'text-secondary': '#A8B7CC',
        'text-muted': '#6E7E96',
        'text-inverse': '#070B14',
        'accent-cyan': '#22D3EE',
        'accent-cyan-glow': 'rgba(34,211,238,0.14)',
        'success-green': '#34D399',
        'success-green-glow': 'rgba(52,211,153,0.12)',
        'danger-red': '#F87171',
        'danger-red-glow': 'rgba(248,113,113,0.12)',
        'warning-amber': '#FBBF24',
        'info-purple': '#A78BFA',
        'border-subtle': '#1C2840',
        'border-active': '#22D3EE',
        'border-success': '#34D399',
        'border-danger': '#F87171',
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
      },
      fontFamily: {
        inter: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // Global readability lift: text-xs was 12px and is the app's dominant
        // body size (240+ uses). 13px keeps density while staying legible.
        // text-2xs is the sanctioned micro-label size (replaces ad-hoc
        // text-[10px]) — pair with uppercase + tracking-wider.
        '2xs': ['0.6875rem', { lineHeight: '0.875rem', letterSpacing: '0.02em' }],
        xs: ['0.8125rem', { lineHeight: '1.25rem' }],
        sm: ['0.875rem', { lineHeight: '1.4rem' }],
      },
      borderRadius: {
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xs: "calc(var(--radius) - 6px)",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        // Card depth: a hairline top highlight + soft drop. Surfaces read as
        // raised panels instead of outlined rectangles.
        card: "inset 0 1px 0 0 rgba(255,255,255,0.04), 0 10px 30px -16px rgba(0,0,0,0.65)",
        "card-hover": "inset 0 1px 0 0 rgba(255,255,255,0.06), 0 16px 40px -16px rgba(0,0,0,0.7), 0 0 0 1px rgba(34,211,238,0.12)",
        "glow-cyan": "0 0 28px -8px rgba(34,211,238,0.45)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "caret-blink": {
          "0%,70%,100%": { opacity: "1" },
          "20%,50%": { opacity: "0" },
        },
        "pulse-dot": {
          "0%, 100%": { transform: "scale(1)", opacity: "0.8" },
          "50%": { transform: "scale(1.3)", opacity: "0.4" },
        },
        "marquee": {
          "0%": { transform: "translateX(0%)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "caret-blink": "caret-blink 1.25s ease-out infinite",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
        "marquee": "marquee 30s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
