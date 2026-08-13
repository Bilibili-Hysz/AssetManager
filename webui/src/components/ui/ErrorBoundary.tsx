import { Component, type ErrorInfo, type ReactNode } from 'react';
import { t, subscribeToLang } from '../../i18n';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/**
 * Top-level error boundary. Catches render/lifecycle errors anywhere below it
 * and shows a recoverable fallback instead of a blank screen.
 *
 * It is a class component (required for error boundaries), so it consumes the
 * i18n module directly (`t` + `subscribeToLang`) instead of the `useI18n` hook.
 */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  private unsubscribe: (() => void) | null = null;

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] render failed:', error, errorInfo.componentStack);
  }

  componentDidMount(): void {
    // Keep the fallback text in sync when the user switches language.
    this.unsubscribe = subscribeToLang(() => this.forceUpdate());
  }

  componentWillUnmount(): void {
    this.unsubscribe?.();
  }

  private handleRetry = (): void => {
    window.location.reload();
  };

  private handleGoHome = (): void => {
    window.location.href = '/';
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[var(--color-bg)] px-4 text-center">
        <h1 className="text-2xl font-semibold text-[var(--color-text)]">{t('error.unknown')}</h1>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={this.handleRetry}
            className="rounded-lg px-4 py-2 font-medium transition-theme hover:opacity-90"
            style={{ backgroundColor: '#4f46e5', color: '#ffffff' }}
          >
            {t('landing.retry')}
          </button>
          <button
            type="button"
            onClick={this.handleGoHome}
            className="rounded-lg border border-[var(--color-border-strong)] px-4 py-2 font-medium text-[var(--color-text)] transition-theme hover:bg-[var(--color-surface-hover)]"
          >
            {t('gallery.back_to_gallery')}
          </button>
        </div>
      </div>
    );
  }
}
