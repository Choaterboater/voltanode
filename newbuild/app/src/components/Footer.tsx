import { Heart } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="border-t border-border-subtle bg-bg-base px-6 py-4">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-2 sm:flex-row">
        <span className="text-xs text-text-muted">
          v1.0.0 · Paper Trading Mode
        </span>
        <span className="text-xs text-text-muted">
          Built with{' '}
          <Heart className="inline h-3 w-3 text-danger-red fill-danger-red" />{' '}
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
    </footer>
  );
}
