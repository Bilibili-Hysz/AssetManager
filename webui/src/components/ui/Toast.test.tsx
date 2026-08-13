// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider, useToast } from './Toast';

function ErrorToast() {
  const { showToast } = useToast();
  useEffect(() => showToast('Upload failed', 'error'), [showToast]);
  return null;
}

function SuccessToast() {
  const { showToast } = useToast();
  useEffect(() => showToast('Saved', 'success'), [showToast]);
  return null;
}

describe('ToastProvider', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('announces errors assertively and labels the dismiss control', () => {
    render(<ToastProvider><ErrorToast /></ToastProvider>);

    expect(screen.getByRole('alert').textContent).toContain('Upload failed');
    expect(screen.getByRole('button', { name: 'Close' })).toBeDefined();
  });

  it('dismisses success toasts after 4 seconds', () => {
    vi.useFakeTimers();
    render(<ToastProvider><SuccessToast /></ToastProvider>);

    expect(screen.getByRole('status')).toBeDefined();
    act(() => vi.advanceTimersByTime(3999));
    expect(screen.getByRole('status')).toBeDefined();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('keeps error toasts for 8 seconds', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ErrorToast /></ToastProvider>);

    act(() => vi.advanceTimersByTime(4000));
    expect(screen.getByRole('alert')).toBeDefined();
    act(() => vi.advanceTimersByTime(3999));
    expect(screen.getByRole('alert')).toBeDefined();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('pauses the dismiss timer while hovered and re-arms it on leave', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ErrorToast /></ToastProvider>);

    const alert = screen.getByRole('alert');
    fireEvent.mouseEnter(alert);
    // Far beyond any dismiss deadline: hovering must keep it visible.
    act(() => vi.advanceTimersByTime(60000));
    expect(screen.getByRole('alert')).toBeDefined();

    fireEvent.mouseLeave(alert);
    act(() => vi.advanceTimersByTime(7999));
    expect(screen.getByRole('alert')).toBeDefined();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('clears a pending timer when dismissed manually', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ErrorToast /></ToastProvider>);

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('alert')).toBeNull();
    // Advancing past the deadline must not resurrect the toast.
    act(() => vi.advanceTimersByTime(60000));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
