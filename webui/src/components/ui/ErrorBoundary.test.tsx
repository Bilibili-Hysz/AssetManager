// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ErrorBoundary from './ErrorBoundary';

function Bomb(): never {
  throw new Error('render exploded');
}

function Healthy() {
  return <div>healthy content</div>;
}

describe('ErrorBoundary', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders children when nothing throws', () => {
    render(<ErrorBoundary><Healthy /></ErrorBoundary>);
    expect(screen.getByText('healthy content')).toBeDefined();
  });

  it('shows a recoverable fallback when a child throws', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    // The boundary consumes the i18n module directly, so the fallback shows
    // the real English translations.
    expect(screen.getByText('An unexpected error occurred.')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDefined();
    expect(screen.getByRole('button', { name: 'Back to gallery' })).toBeDefined();
    errorSpy.mockRestore();
  });

  it('reloads the page on retry', () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    screen.getByRole('button', { name: 'Retry' }).click();
    expect(reload).toHaveBeenCalledTimes(1);
    errorSpy.mockRestore();
  });

  it('navigates home from the fallback', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    screen.getByRole('button', { name: 'Back to gallery' }).click();
    expect(window.location.pathname).toBe('/');
    errorSpy.mockRestore();
  });
});
