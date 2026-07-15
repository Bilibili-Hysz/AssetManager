// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { describe, expect, it } from 'vitest';
import { ToastProvider, useToast } from './Toast';

function ErrorToast() {
  const { showToast } = useToast();
  useEffect(() => showToast('Upload failed', 'error'), [showToast]);
  return null;
}

describe('ToastProvider', () => {
  it('announces errors assertively and labels the dismiss control', () => {
    render(<ToastProvider><ErrorToast /></ToastProvider>);

    expect(screen.getByRole('alert').textContent).toContain('Upload failed');
    expect(screen.getByRole('button', { name: 'Close' })).toBeDefined();
  });
});
