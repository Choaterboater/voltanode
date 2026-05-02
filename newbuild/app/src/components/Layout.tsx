import type { ReactNode } from 'react';
import Navbar from './Navbar';
import Footer from './Footer';

interface LayoutProps {
  children: ReactNode;
  title: string;
  rightContent?: ReactNode;
}

export default function Layout({ children, title, rightContent }: LayoutProps) {
  return (
    <div className="flex min-h-[100dvh] w-full bg-bg-base overflow-x-hidden">
      <Navbar />

      {/* Main content area */}
      <div className="flex min-w-0 flex-1 flex-col lg:ml-[260px]">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border-subtle bg-bg-base px-4 sm:px-6">
          <h1 className="truncate text-lg font-semibold text-text-primary">{title}</h1>
          {rightContent && <div className="flex shrink-0 items-center gap-2 sm:gap-4">{rightContent}</div>}
        </header>

        {/* Content */}
        <main className="flex-1 overflow-x-hidden p-4 sm:p-6">{children}</main>

        <Footer />
      </div>
    </div>
  );
}
