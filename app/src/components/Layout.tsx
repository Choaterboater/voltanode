import type { ReactNode } from 'react';
import Navbar from './Navbar';
import Footer from './Footer';
import RestartBackendButton from './RestartBackendButton';

interface LayoutProps {
  children: ReactNode;
  title?: string;
  rightContent?: ReactNode;
}

export default function Layout({ children, title, rightContent }: LayoutProps) {
  return (
    // No bg on the shell — the body paints a layered radial-gradient backdrop
    // and an opaque div would flatten it back to a slab.
    <div className="flex min-h-[100dvh]">
      <Navbar />

      {/* Main content area. `min-w-0` lets flex-1 shrink below the inner
          main's max-w when viewport - sidebar is narrower than 1600px,
          which prevents the column from overflowing past the viewport. */}
      <div className="flex min-w-0 flex-1 flex-col lg:ml-[248px]">
        {/* Top bar is now always rendered so the persistent Restart-backend
            button is reachable from any page. Title is still optional — pages
            with rich in-body heroes (Watchlist, Advisor, Squeeze, About)
            omit it so we don't render the page name twice. */}
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border-subtle bg-bg-base/75 px-6 backdrop-blur-xl">
          {title ? (
            <h1 className="text-[17px] font-semibold tracking-tight text-text-primary">{title}</h1>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-4">
            {rightContent}
            <RestartBackendButton />
          </div>
        </header>

        {/* Content */}
        <main className="mx-auto w-full max-w-[1600px] flex-1 p-6 lg:p-7">{children}</main>

        <Footer />
      </div>
    </div>
  );
}
