// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTheme } from './useTheme';

function installMediaQuery(matches: boolean) {
  let current = matches;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  let addEventListenerCalls = 0;
  let removeEventListenerCalls = 0;
  let addListenerCalls = 0;
  let removeListenerCalls = 0;
  const media = {
    get matches() { return current; },
    media: '(prefers-color-scheme: dark)',
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => { addEventListenerCalls += 1; listeners.add(listener); },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => { removeEventListenerCalls += 1; listeners.delete(listener); },
    addListener: (listener: (event: MediaQueryListEvent) => void) => { addListenerCalls += 1; listeners.add(listener); },
    removeListener: (listener: (event: MediaQueryListEvent) => void) => { removeListenerCalls += 1; listeners.delete(listener); },
    dispatch(next: boolean) {
      current = next;
      listeners.forEach(listener => listener({ matches: next } as MediaQueryListEvent));
    },
    get listenerCount() { return listeners.size; },
    get addEventListenerCalls() { return addEventListenerCalls; },
    get removeEventListenerCalls() { return removeEventListenerCalls; },
    get addListenerCalls() { return addListenerCalls; },
    get removeListenerCalls() { return removeListenerCalls; },
  };
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => media) });
  return media;
}

describe('useTheme', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.style.colorScheme = '';
    vi.unstubAllGlobals();
  });

  it('uses the stored theme before browser prefers-color-scheme', () => {
    localStorage.setItem('am_theme', 'light');
    installMediaQuery(true);

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe('light');
  });

  it('falls back to browser prefers-color-scheme when no user setting exists', () => {
    installMediaQuery(true);

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe('dark');
  });

  it('migrates the legacy Gate theme key to am_theme', () => {
    localStorage.setItem('assets-manager.gate-theme', 'light');
    installMediaQuery(true);

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe('light');
    expect(localStorage.getItem('am_theme')).toBe('light');
    expect(localStorage.getItem('assets-manager.gate-theme')).toBeNull();
  });

  it('allows callers to explicitly select the light theme', () => {
    installMediaQuery(true);
    const { result } = renderHook(() => useTheme());

    act(() => result.current.setTheme('light'));

    expect(result.current.theme).toBe('light');
    expect(localStorage.getItem('am_theme')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('keeps two mounted consumers synchronized', () => {
    installMediaQuery(false);
    const first = renderHook(() => useTheme());
    const second = renderHook(() => useTheme());

    act(() => first.result.current.toggleTheme());

    expect(first.result.current.theme).toBe('dark');
    expect(second.result.current.theme).toBe('dark');
  });

  it('updates document class, data-theme, and color scheme', () => {
    installMediaQuery(true);
    const { result } = renderHook(() => useTheme());

    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(document.documentElement.classList.contains('light')).toBe(false);
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');

    act(() => result.current.toggleTheme());

    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
  });

  it('registers one media listener and removes it when the last consumer unmounts', () => {
    const media = installMediaQuery(false);
    const first = renderHook(() => useTheme());
    const second = renderHook(() => useTheme());

    expect(media.addEventListenerCalls).toBe(1);
    expect(media.addListenerCalls).toBe(0);
    expect(media.listenerCount).toBe(1);

    first.unmount();
    expect(media.listenerCount).toBe(1);
    second.unmount();
    expect(media.removeEventListenerCalls).toBe(1);
    expect(media.removeListenerCalls).toBe(0);
    expect(media.listenerCount).toBe(0);
  });

  it('re-subscribes exactly once after all consumers unmount', () => {
    const media = installMediaQuery(false);
    const first = renderHook(() => useTheme());
    first.unmount();

    const second = renderHook(() => useTheme());

    expect(media.addEventListenerCalls).toBe(2);
    expect(media.listenerCount).toBe(1);
    second.unmount();
    expect(media.removeEventListenerCalls).toBe(2);
  });
});
