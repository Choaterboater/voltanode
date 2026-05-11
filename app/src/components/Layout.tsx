import type { ReactNode } from 'react';
import Navbar from './Navbar';
import Footer from './Footer';

interface LayoutProps {
  children: ReactNode;
  title?: string;
  rightContent?: ReactNode;
}

export default function Layout({ children, title, rightContent }: LayoutProps) {
  return (
    <div className="flex min-h-[100dvh] bg-bg-base">
      <Navbar />

      {/* Main content area. `min-w-0` lets flex-1 shrink below the inner
          main's max-w when viewport - sidebar is narrower than 1600px,
          which prevents the column from overflowing past the viewport. */}
      <div className="flex min-w-0 flex-1 flex-col lg:ml-[260px]">
        {/* Top bar. Title is optional — pages with rich in-body heroes
            (Watchlist, Advisor, Squeeze, About) omit it so we don't render
            the page name twice. */}
        {(title || rightContent) && (
          <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border-subtle bg-bg-base px-6">
            {title ? (
              <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
            ) : (
              <span />
            )}
            {rightContent && <div className="flex items-center gap-4">{rightContent}</div>}
          </header>
        )}

        {/* Content */}
        <main className="mx-auto w-full max-w-[1600px] flex-1 p-6">{children}</main>

        <Footer />
      </div>
    </div>
  );
}
