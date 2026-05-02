import { NavLink, useLocation, useNavigate } from 'react-router';
import {
  LayoutDashboard,
  Wallet,
  LineChart,
  BarChart3,
  PieChart,
  Bot,
  Newspaper,
  Sparkles,
  Info,
  Settings,
  Plug,
  Loader2,
  Eye,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { useSettings } from '@/hooks/useSettings';

const navItems = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard },
  { label: 'Watchlist', path: '/watchlist', icon: Eye },
  { label: 'Advisor', path: '/advisor', icon: Sparkles },
  { label: 'Paper Trading', path: '/paper', icon: Wallet },
  { label: 'Strategies', path: '/strategies', icon: LineChart },
  { label: 'Backtest', path: '/backtest', icon: BarChart3 },
  { label: 'Analytics', path: '/analytics', icon: PieChart },
  { label: 'Bot Lab', path: '/bots', icon: Bot },
  { label: 'News', path: '/news', icon: Newspaper },
  { label: 'About', path: '/about', icon: Info },
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
        className="fixed left-4 top-4 z-50 flex h-10 w-10 items-center justify-center rounded-md bg-bg-surface border border-border-subtle text-text-primary lg:hidden"
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
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex flex-col w-[260px] transform border-r border-border-subtle bg-bg-surface transition-transform duration-300 lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Logo area */}
        <div className="flex h-16 flex-col justify-center px-5">
          <div className="flex items-center gap-2.5">
            <img src="./logo-icon.svg" alt="" className="h-7 w-7" />
            <span className="text-lg font-bold tracking-tight text-text-primary">
              Volta<span className="text-accent-cyan">Node</span>
            </span>
          </div>
          <span className="mt-0.5 pl-[44px] text-[10px] text-text-muted tracking-wide">
            by{' '}
            <a
              href="https://choatelabs.app/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-cyan hover:underline"
            >
              Choate Labs
            </a>
          </span>
        </div>

        {/* Connection badge */}
        <div className="mx-4 mb-2">
          <button
            onClick={() => { navigate('/settings'); setMobileOpen(false); }}
            className="flex w-full items-center gap-2 rounded-md border border-border-subtle bg-bg-input px-3 py-2 text-xs transition-colors hover:bg-bg-elevated"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" />
            ) : (
              <span
                className={`h-2 w-2 rounded-full ${
                  backendOffline
                    ? 'bg-danger-red'
                    : brokerConnected
                    ? isLive
                      ? 'bg-danger-red animate-pulse'
                      : 'bg-success-green'
                    : 'bg-text-muted'
                }`}
              />
            )}
            <span className="text-text-secondary truncate">
              {backendOffline
                ? 'Backend offline'
                : loading
                ? 'Checking...'
                : brokerConnected
                ? `${brokerName.charAt(0).toUpperCase() + brokerName.slice(1)} · ${isLive ? 'LIVE' : 'Paper'}`
                : 'No broker connected'}
            </span>
            <Plug className="ml-auto h-3 w-3 text-text-muted" />
          </button>
        </div>

        {/* Nav items */}
        <nav className="mt-2 px-3 flex-1 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={() => setMobileOpen(false)}
                className={`flex h-11 items-center rounded-lg px-4 text-sm font-medium transition-colors ${
                  isActive
                    ? 'border-l-[3px] border-l-accent-cyan bg-accent-cyan-glow text-accent-cyan'
                    : 'text-text-secondary hover:bg-bg-input hover:text-text-primary'
                }`}
              >
                <Icon className="mr-3 h-5 w-5" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        {/* Settings link at bottom */}
        <div className="px-3 pb-3">
          <NavLink
            to="/settings"
            onClick={() => setMobileOpen(false)}
            className={`flex h-10 items-center rounded-lg px-4 text-xs font-medium transition-colors ${
              location.pathname === '/settings'
                ? 'border-l-[3px] border-l-accent-cyan bg-accent-cyan-glow text-accent-cyan'
                : 'text-text-muted hover:bg-bg-input hover:text-text-secondary'
            }`}
          >
            <Settings className="mr-3 h-4 w-4" />
            Settings
          </NavLink>
        </div>
      </aside>
    </>
  );
}
