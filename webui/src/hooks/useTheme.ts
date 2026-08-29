import { useCallback, useEffect, useSyncExternalStore } from 'react';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'am_theme';
const LEGACY_STORAGE_KEY = 'assets-manager.gate-theme';
const MEDIA_QUERY = '(prefers-color-scheme: dark)';

type ThemeListener = () => void;
let currentTheme: Theme | null = null;
const listeners = new Set<ThemeListener>();
let mediaQuery: MediaQueryList | null = null;
let mediaHandler: ((event: MediaQueryListEvent) => void) | null = null;

function isTheme(value: string | null): value is Theme {
  return value === 'dark' || value === 'light';
}

/**
 * The visitor's explicit mode preference ('dark' | 'light'), or null when
 * running in auto mode (no stored preference — 'auto' also reads as null).
 * Exported for useServerTheme, which must distinguish explicit overrides
 * from the system-preference fallback.
 */
export function readStoredThemePreference(): Theme | null {
  return readStoredTheme();
}

function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isTheme(stored)) return stored;
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (isTheme(legacy)) {
      localStorage.setItem(STORAGE_KEY, legacy);
      localStorage.removeItem(LEGACY_STORAGE_KEY);
      return legacy;
    }
  } catch {
    // Browser storage may be unavailable.
  }
  return null;
}

function resolveTheme(): Theme {
  const stored = readStoredTheme();
  if (stored) return stored;
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(MEDIA_QUERY).matches
    ? 'dark'
    : 'light';
}

/** Exported for useServerTheme: the identity hook re-applies the mode class
 * after this (same commit, later effect) when it follows the owner theme. */
export function applyDocumentTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.classList.toggle('light', theme === 'light');
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

function setTheme(theme: Theme): void {
  currentTheme = theme;
  applyDocumentTheme(theme);
  try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* ignore */ }
  listeners.forEach(listener => listener());
}

function ensureMediaListener(): void {
  if (mediaQuery || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
  mediaQuery = window.matchMedia(MEDIA_QUERY);
  mediaHandler = () => {
    if (readStoredTheme() || listeners.size === 0) return;
    currentTheme = mediaQuery?.matches ? 'dark' : 'light';
    applyDocumentTheme(currentTheme);
    listeners.forEach(listener => listener());
  };
  if (typeof mediaQuery.addEventListener === 'function') {
    mediaQuery.addEventListener('change', mediaHandler);
  } else {
    mediaQuery.addListener?.(mediaHandler);
  }
}

function subscribe(listener: ThemeListener): () => void {
  listeners.add(listener);
  ensureMediaListener();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      if (mediaQuery && mediaHandler) {
        if (typeof mediaQuery.removeEventListener === 'function') {
          mediaQuery.removeEventListener('change', mediaHandler);
        } else {
          mediaQuery.removeListener?.(mediaHandler);
        }
      }
      currentTheme = null;
      mediaQuery = null;
      mediaHandler = null;
    }
  };
}

function getSnapshot(): Theme {
  return currentTheme ?? resolveTheme();
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, (): Theme => 'dark');

  useEffect(() => {
    applyDocumentTheme(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => setTheme(getSnapshot() === 'dark' ? 'light' : 'dark'), []);

  return { theme, setTheme, toggleTheme };
}
