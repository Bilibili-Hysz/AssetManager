// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DownloadProgressProvider, useDownloadProgress } from './DownloadProgress';

function Controls() {
  const progress = useDownloadProgress();
  return (
    <>
      <button onClick={() => progress.start('Creating ZIP archive')}>Start</button>
      <button onClick={() => progress.update({ loaded: 25, total: 100 })}>Set determinate progress</button>
      <button onClick={() => progress.finish()}>Finish</button>
    </>
  );
}

describe('DownloadProgressProvider', () => {
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
});
