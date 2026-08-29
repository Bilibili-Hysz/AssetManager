// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTheme } from './useTheme';
import {
  findThemeByName,
  readRememberedServerTheme,
  resolveServerThemeIdentity,
  useServerTheme,
} from './useServerTheme';

function installMediaQuery(matches: boolean) {
  const media = {
    matches,
    media: '(prefers-color-scheme: dark)',
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  };
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => media) });
}

describe('resolveServerThemeIdentity (pure branch matrix)', () => {
  it('auto follows the owner theme identity and its own mode', () => {
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: 'Navy', systemDark: true }))
      .toEqual({ mode: 'dark', slug: 'navy' });
    // A light owner theme keeps its light mode even on a dark-OS visitor.
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: 'Mint', systemDark: true }))
      .toEqual({ mode: 'light', slug: 'mint' });
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: 'Mint', systemDark: false }))
      .toEqual({ mode: 'light', slug: 'mint' });
  });

  it('auto falls back to the system mode for unknown or missing names', () => {
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: 'No Such Theme', systemDark: true }))
      .toEqual({ mode: 'dark', slug: null });
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: 'No Such Theme', systemDark: false }))
      .toEqual({ mode: 'light', slug: null });
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: '', systemDark: true }))
      .toEqual({ mode: 'dark', slug: null });
    expect(resolveServerThemeIdentity({ explicitTheme: null, serverThemeName: undefined, systemDark: false }))
      .toEqual({ mode: 'light', slug: null });
  });

  it('explicit light uses the owner theme only when it is a light theme', () => {
    expect(resolveServerThemeIdentity({ explicitTheme: 'light', serverThemeName: 'Mint', systemDark: true }))
      .toEqual({ mode: 'light', slug: 'mint' });
    expect(resolveServerThemeIdentity({ explicitTheme: 'light', serverThemeName: 'Navy', systemDark: true }))
      .toEqual({ mode: 'light', slug: null });
    expect(resolveServerThemeIdentity({ explicitTheme: 'light', serverThemeName: 'No Such Theme', systemDark: true }))
      .toEqual({ mode: 'light', slug: null });
  });

  it('explicit dark uses the owner theme only when it is a dark theme', () => {
    expect(resolveServerThemeIdentity({ explicitTheme: 'dark', serverThemeName: 'Navy', systemDark: false }))
      .toEqual({ mode: 'dark', slug: 'navy' });
    expect(resolveServerThemeIdentity({ explicitTheme: 'dark', serverThemeName: 'Mint', systemDark: false }))
      .toEqual({ mode: 'dark', slug: null });
    expect(resolveServerThemeIdentity({ explicitTheme: 'dark', serverThemeName: 'No Such Theme', systemDark: false }))
      .toEqual({ mode: 'dark', slug: null });
  });

  it('matches owner theme names case-insensitively', () => {
    expect(findThemeByName('rose pine')?.slug).toBe('rose-pine');
    expect(findThemeByName('  NAVY  ')?.slug).toBe('navy');
    expect(findThemeByName(null)).toBeNull();
    expect(findThemeByName(undefined)).toBeNull();
  });
});

describe('useServerTheme (document identity effects)', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.removeAttribute('data-am-theme');
    document.documentElement.style.colorScheme = '';
    vi.unstubAllGlobals();
  });

  it('applies the owner slug and owner mode in auto mode', () => {
    installMediaQuery(true); // visitor OS is dark
    const { result } = renderHook(() => useServerTheme('Mint'));

    expect(result.current).toEqual({ mode: 'light', slug: 'mint' });
    expect(document.documentElement.getAttribute('data-am-theme')).toBe('mint');
    // Owner mode wins over the system preference so light-theme contrast
    // tokens (accent-text, shadows, color-scheme) stay correct.
    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    // Remembered for the pre-paint inline script on the next visit.
    expect(readRememberedServerTheme()).toEqual({ name: 'Mint', slug: 'mint', dark: false });
  });

  it('removes the identity attribute when no owner theme matches', () => {
    installMediaQuery(false);
    document.documentElement.setAttribute('data-am-theme', 'stale');
    const { result } = renderHook(() => useServerTheme('No Such Theme'));

    expect(result.current.slug).toBeNull();
    expect(document.documentElement.hasAttribute('data-am-theme')).toBe(false);
    expect(localStorage.getItem('am_server_theme')).toBeNull();
  });

  it('explicit light mode on a dark owner theme falls back to L_Dawn', () => {
    localStorage.setItem('am_theme', 'light');
    installMediaQuery(true);
    const { result } = renderHook(() => useServerTheme('Navy'));

    expect(result.current).toEqual({ mode: 'light', slug: null });
    expect(document.documentElement.hasAttribute('data-am-theme')).toBe(false);
    expect(document.documentElement.classList.contains('light')).toBe(true);
  });

  it('explicit light mode on a light owner theme keeps the full identity', () => {
    localStorage.setItem('am_theme', 'light');
    installMediaQuery(true);
    const { result } = renderHook(() => useServerTheme('Mint'));

    expect(result.current).toEqual({ mode: 'light', slug: 'mint' });
    expect(document.documentElement.getAttribute('data-am-theme')).toBe('mint');
    expect(document.documentElement.classList.contains('light')).toBe(true);
  });

  it('explicit dark mode on a dark owner theme keeps the full identity', () => {
    localStorage.setItem('am_theme', 'dark');
    installMediaQuery(false);
    const { result } = renderHook(() => useServerTheme('Navy'));

    expect(result.current).toEqual({ mode: 'dark', slug: 'navy' });
    expect(document.documentElement.getAttribute('data-am-theme')).toBe('navy');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('explicit dark mode on a light owner theme falls back to L_Dawn', () => {
    localStorage.setItem('am_theme', 'dark');
    installMediaQuery(false);
    const { result } = renderHook(() => useServerTheme('Mint'));

    expect(result.current).toEqual({ mode: 'dark', slug: null });
    expect(document.documentElement.hasAttribute('data-am-theme')).toBe(false);
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('toggles re-resolve the identity: auto -> explicit light -> explicit dark', () => {
    installMediaQuery(true);
    const theme = renderHook(() => useTheme());
    const { result } = renderHook(() => useServerTheme('Navy'));

    // No stored preference -> auto -> full owner identity.
    expect(result.current).toEqual({ mode: 'dark', slug: 'navy' });
    expect(document.documentElement.getAttribute('data-am-theme')).toBe('navy');

    // Visitor toggles to explicit light -> owner (dark) theme must yield.
    act(() => theme.result.current.setTheme('light'));
    expect(result.current).toEqual({ mode: 'light', slug: null });
    expect(document.documentElement.hasAttribute('data-am-theme')).toBe(false);

    // Toggle back -> explicit dark identity again.
    act(() => theme.result.current.setTheme('dark'));
    expect(result.current).toEqual({ mode: 'dark', slug: 'navy' });
    expect(document.documentElement.getAttribute('data-am-theme')).toBe('navy');
  });
});
