import * as React from 'react';

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleGoHome = () => {
    this.setState({ hasError: false, error: undefined });
    window.location.href = '/board';
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center bg-bg-primary">
          <div className="max-w-md rounded-lg border border-border-soft bg-bg-secondary p-8 text-center shadow-sm">
            <h2 className="text-lg font-semibold text-text-primary">
              页面发生错误
            </h2>
            <p className="mt-2 text-sm text-text-secondary">
              应用遇到了意外错误。可以尝试刷新页面或返回首页。
            </p>
            {import.meta.env.DEV && this.state.error && (
              <pre className="mt-4 max-h-40 overflow-auto rounded bg-bg-tertiary p-3 text-left text-xs text-danger">
                {this.state.error.message}
              </pre>
            )}
            <div className="mt-6 flex justify-center gap-3">
              <button
                onClick={this.handleReload}
                className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600"
              >
                刷新页面
              </button>
              <button
                onClick={this.handleGoHome}
                className="rounded-md border border-border-default px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-bg-tertiary"
              >
                返回首页
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
