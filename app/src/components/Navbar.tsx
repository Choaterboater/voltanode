import { NavLink, useLocation, useNavigate } from 'react-router';
import {
  LayoutDashboard,
  Wallet,
  LineChart,
  BarChart3,
  PieChart,
  Bot,
  Newspaper,
  Activity,
  Sparkles,
  Flame,
  Anchor,
  Info,
  Settings,
  Plug,
  Loader2,
  Eye,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { useSettings } from '@/hooks/useSettings';

const navGroups = [
  {
    label: 'Trade',
    items: [
      { label: 'Dashboard', path: '/', icon: LayoutDashboard },
      { label: 'Paper Trading', path: '/paper', icon: Wallet },
      { label: 'Strategies', path: '/strategies', icon: LineChart },
      { label: 'Bot Lab', path: '/bots', icon: Bot },
    ],
  },
  {
    label: 'Research',
    items: [
      { label: 'Watchlist', path: '/watchlist', icon: Eye },
      { label: 'Advisor', path: '/advisor', icon: Sparkles },
      { label: 'Squeeze', path: '/squeeze', icon: Flame },
      { label: 'Long-Term', path: '/long-term', icon: Anchor },
      { label: 'News', path: '/news', icon: Newspaper },
      { label: 'News Analytics', path: '/news-analytics', icon: Activity },
    ],
  },
  {
    label: 'Analyze',
    items: [
      { label: 'Backtest', path: '/backtest', icon: BarChart3 },
      { label: 'Analytics', path: '/analytics', icon: PieChart },
      { label: 'About', path: '/about', icon: Info },
    ],
  },
];

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { liveMode, getLiveMode, loading } = useSettings();

  const [backendOffline, setBackendOffline] = useState(false);

  useEffect(() => {
    const check = async () => {
      try {
        await getLiveMode();
        setBackendOffline(false);
      } catch {
        setBackendOffline(true);
      }
    };
    check();
    const interval = setInterval(() => check(), 15000);
    return () => clearInterval(interval);
  }, [getLiveMode]);

  const brokerConnected = liveMode?.broker_connected ?? false;
  const brokerName = liveMode?.broker_name ?? '';
  const isLive = liveMode?.live_mode ?? false;

  return (
    <>
      {/* Mobile toggle */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="fixed left-4 top-4 z-50 flex h-10 w-10 items-center justify-center rounded-lg border border-border-subtle bg-bg-surface text-text-primary shadow-card lg:hidden"
      >
        <span className="sr-only">Toggle menu</span>
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          {mobileOpen ? (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          )}
        </svg>
      </button>

      {/* Overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[248px] transform flex-col border-r border-border-subtle bg-bg-input/80 backdrop-blur-xl transition-transform duration-300 lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Logo area */}
        <div className="flex h-16 items-center gap-3 px-5">
          <img src="./logo-icon.svg" alt="" className="h-8 w-8" />
          <div className="flex flex-col">
            <span className="text-[17px] font-bold leading-5 tracking-tight text-text-primary">
              Volta<span className="text-accent-cyan">Node</span>
            </span>
            <a
              href="https://choatelabs.app/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-2xs text-text-muted transition-colors hover:text-accent-cyan"
            >
              by Choate Labs
            </a>
          </div>
        </div>

        {/* Connection badge */}
        <div className="mx-4 mb-1">
          <button
            onClick={() => { navigate('/settings'); setMobileOpen(false); }}
            className="flex w-full items-center gap-2.5 rounded-lg border border-border-subtle bg-bg-surface px-3 py-2.5 text-xs shadow-card transition-colors hover:border-accent-cyan/30"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" />
            ) : (
              <span className="relative flex h-2 w-2">
                {!backendOffline && brokerConnected && (
                  <span
                    className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-50 ${
                      isLive ? 'bg-danger-red' : 'bg-success-green'
                    }`}
                  />
                )}
                <span
                  className={`relative inline-flex h-2 w-2 rounded-full ${
                    backendOffline
                      ? 'bg-danger-red'
                      : brokerConnected
                      ? isLive
                        ? 'bg-danger-red'
                        : 'bg-success-green'
                      : 'bg-text-muted'
                  }`}
                />
              </span>
            )}
            <span className="truncate font-medium text-text-secondary">
              {backendOffline
                ? 'Backend offline'
                : loading
                ? 'Checking...'
                : brokerConnected
                ? `${brokerName.charAt(0).toUpperCase() + brokerName.slice(1)} · ${isLive ? 'LIVE' : 'Paper'}`
                : 'No broker connected'}
            </span>
            <Plug className="ml-auto h-3.5 w-3.5 shrink-0 text-text-muted" />
          </button>
        </div>

        {/* Nav items */}
        <nav className="flex-1 overflow-y-auto px-3 pb-4 pt-2">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-1">
              <p className="px-3 pb-1 pt-3 text-2xs font-semibold uppercase tracking-[0.14em] text-text-muted/70">
                {group.label}
              </p>
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = location.pathname === item.path;
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    onClick={() => setMobileOpen(false)}
                    className={`group relative mb-0.5 flex h-9 items-center rounded-lg px-3 text-[13px] font-medium transition-colors ${
                      isActive
                        ? 'bg-accent-cyan/10 text-accent-cyan'
                        : 'text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary'
                    }`}
                  >
                    {isActive && (
                      <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent-cyan shadow-glow-cyan" />
                    )}
                    <Icon
                      className={`mr-3 h-4 w-4 transition-colors ${
                        isActive ? 'text-accent-cyan' : 'text-text-muted group-hover:text-text-secondary'
                      }`}
                    />
                    {item.label}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Settings link at bottom */}
        <div className="border-t border-border-subtle px-3 py-3">
          <NavLink
            to="/settings"
            onClick={() => setMobileOpen(false)}
            className={`group relative flex h-9 items-center rounded-lg px-3 text-[13px] font-medium transition-colors ${
              location.pathname === '/settings'
                ? 'bg-accent-cyan/10 text-accent-cyan'
                : 'text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary'
            }`}
          >
            {location.pathname === '/settings' && (
              <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent-cyan shadow-glow-cyan" />
            )}
            <Settings
              className={`mr-3 h-4 w-4 ${
                location.pathname === '/settings' ? 'text-accent-cyan' : 'text-text-muted group-hover:text-text-secondary'
              }`}
            />
            Settings
          </NavLink>
        </div>
      </aside>
    </>
  );
}
