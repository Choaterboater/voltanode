import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-bg-base px-6">
          <div className="w-full max-w-md rounded-[10px] border border-border-subtle bg-bg-surface p-6 text-center">
            <h2 className="text-lg font-semibold text-text-primary">Something went wrong</h2>
            <p className="mt-2 text-sm text-text-secondary">
              An unexpected error occurred. Please reload the page to continue.
            </p>
            {this.state.error && (
              <pre className="mt-4 max-h-32 overflow-auto rounded-md bg-bg-input p-3 text-left text-xs text-danger-red">
                {this.state.error.message}
              </pre>
            )}
            <button
              onClick={this.handleReload}
              className="mt-5 inline-flex items-center justify-center rounded-md bg-accent-cyan px-4 py-2 text-sm font-medium text-text-inverse hover:brightness-110 transition-all"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
