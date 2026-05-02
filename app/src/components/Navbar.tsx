import { NavLink, useLocation } from 'react-router';
import {
  LayoutDashboard,
  Wallet,
  LineChart,
  BarChart3,
  PieChart,
  Bot,
  Newspaper,
} from 'lucide-react';
import { useState } from 'react';

const navItems = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard },
  { label: 'Paper Trading', path: '/paper', icon: Wallet },
  { label: 'Strategies', path: '/strategies', icon: LineChart },
  { label: 'Backtest', path: '/backtest', icon: BarChart3 },
  { label: 'Analytics', path: '/analytics', icon: PieChart },
  { label: 'Bot Lab', path: '/bots', icon: Bot },
  { label: 'News', path: '/news', icon: Newspaper },
];

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

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
        className={`fixed inset-y-0 left-0 z-40 w-[260px] transform border-r border-border-subtle bg-bg-surface transition-transform duration-300 lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Logo area */}
        <div className="flex h-16 items-center gap-2.5 px-5">
          <img src="./logo-icon.svg" alt="" className="h-7 w-7" />
          <span className="text-lg font-bold tracking-tight text-text-primary">
            Volta<span className="text-accent-cyan">Node</span>
          </span>
        </div>

        {/* Nav items */}
        <nav className="mt-4 px-3">
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
      </aside>
    </>
  );
}
