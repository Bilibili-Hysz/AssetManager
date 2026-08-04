// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { DownloadProgressProvider, useDownloadProgress } from './DownloadProgress';

function Controls() {
  const progress = useDownloadProgress();
  return (
    <>
      <button type="button" onClick={() => progress.start('Creating ZIP archive')}>Start</button>
      <button type="button" onClick={() => progress.update({ loaded: 25, total: 100 })}>Set determinate progress</button>
      <button type="button" onClick={() => progress.finish()}>Finish</button>
    </>
  );
}

function DownloadProgressConsumer() {
  const progress = useDownloadProgress();
  return (
    <>
      <button type="button" data-testid="start-no-label" onClick={() => progress.start()}>Start</button>
      <button type="button" data-testid="update-null-total" onClick={() => progress.update({ loaded: 50, total: null })}>Null total</button>
      <button type="button" data-testid="update-over100" onClick={() => progress.update({ loaded: 200, total: 100 })}>Over 100</button>
    </>
  );
}

describe('DownloadProgressProvider', () => {
  afterEach(() => { cleanup(); });
  it('exposes determinate and indeterminate progress accessibly', () => {
    render(<DownloadProgressProvider><Controls /></DownloadProgressProvider>);

    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    const indeterminate = screen.getByRole('progressbar', { name: 'Creating ZIP archive' });
    expect(indeterminate.getAttribute('aria-busy')).toBe('true');
    expect(indeterminate.getAttribute('data-download-state')).toBe('indeterminate');

    fireEvent.click(screen.getByRole('button', { name: 'Set determinate progress' }));
    const determinate = screen.getByRole('progressbar', { name: 'Creating ZIP archive' });
    expect(determinate.getAttribute('data-download-state')).toBe('determinate');
    expect(determinate.getAttribute('aria-valuenow')).toBe('25');
    expect(determinate.getAttribute('aria-valuetext')).toBe('25%');

    fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
    expect(screen.queryByRole('progressbar', { name: 'Creating ZIP archive' })).toBeNull();
  });

  it('uses default label when start is called without argument', () => {
    render(
      <DownloadProgressProvider>
        <DownloadProgressConsumer />
      </DownloadProgressProvider>,
    );
    fireEvent.click(screen.getByTestId('start-no-label'));
    expect(screen.getByRole('progressbar', { name: 'Download in progress' })).toBeDefined();
  });

  it('stays indeterminate when update receives null total', () => {
    render(
      <DownloadProgressProvider>
        <DownloadProgressConsumer />
      </DownloadProgressProvider>,
    );
    fireEvent.click(screen.getByTestId('start-no-label'));
    fireEvent.click(screen.getByTestId('update-null-total'));
    const bar = screen.getByRole('progressbar', { name: 'Download in progress' });
    expect(bar.getAttribute('data-download-state')).toBe('indeterminate');
    expect(bar.getAttribute('aria-valuenow')).toBeNull();
  });

  it('clamps progress to 100 when loaded exceeds total', () => {
    render(
      <DownloadProgressProvider>
        <DownloadProgressConsumer />
      </DownloadProgressProvider>,
    );
    fireEvent.click(screen.getByTestId('start-no-label'));
    fireEvent.click(screen.getByTestId('update-over100'));
    const bar = screen.getByRole('progressbar', { name: 'Download in progress' });
    expect(bar.getAttribute('aria-valuenow')).toBe('100');
  });
});
