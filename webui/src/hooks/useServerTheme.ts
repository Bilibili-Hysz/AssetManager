import { useEffect, useMemo } from 'react';
import { THEMES } from '../tokens/themes.manifest.generated';
import { applyDocumentTheme, readStoredThemePreference, useTheme, type Theme } from './useTheme';

/**
 * Follow-the-owner theme identity (design line A1): /api/info reports the
 * library owner's current desktop theme as `theme_name`, and the WebUI
 * mirrors it via the `data-am-theme` attribute consumed by
 * themes.generated.css (`html[data-am-theme="<slug>"]` variable blocks).
 *
 * Visitor control stays a light/dark *mode* toggle (am_theme), never a theme
 * picker:
 *   auto            -> full owner-theme identity (slug + owner mode)
 *   explicit light  -> owner theme only if it is a light theme, else the
 *                      L_Dawn fallback (no attribute) + theme_color accent
 *   explicit dark   -> symmetric
 * Unknown theme names (older servers, renamed palettes) fail open to the
 * fallback identity.
 */

export interface ThemeIdentity {
  /** Effective light/dark mode (drives the html.light class + color-scheme). */
  mode: Theme;
  /** Owner theme slug, or null when the fallback palette applies. */
  slug: string | null;
}

interface ManifestTheme {
  name: string;
  slug: string;
  dark: boolean;
}

const SERVER_THEME_STORAGE_KEY = 'am_server_theme';
const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** Resolve a /api/info theme_name against the generated manifest (case-insensitive). */
export function findThemeByName(name: string | null | undefined): ManifestTheme | null {
  if (typeof name !== 'string') return null;
  const needle = name.trim().toLowerCase();
  if (!needle) return null;
  return THEMES.find(theme => theme.name.toLowerCase() === needle) ?? null;
}

/** Pure branch resolution — covered exhaustively by useServerTheme.test.tsx. */
export function resolveServerThemeIdentity(input: {
  explicitTheme: Theme | null;
  serverThemeName: string | null | undefined;
  systemDark: boolean;
}): ThemeIdentity {
  const match = findThemeByName(input.serverThemeName);
  if (input.explicitTheme === 'light') {
    return match && !match.dark ? { mode: 'light', slug: match.slug } : { mode: 'light', slug: null };
  }
  if (input.explicitTheme === 'dark') {
    return match && match.dark ? { mode: 'dark', slug: match.slug } : { mode: 'dark', slug: null };
  }
  // Auto: adopt the owner theme's own mode so a light owner theme keeps its
  // light contrast tokens (accent-text, shadows, color-scheme).
  if (match) return { mode: match.dark ? 'dark' : 'light', slug: match.slug };
  return { mode: input.systemDark ? 'dark' : 'light', slug: null };
}

/** Last server-reported owner theme, persisted for the pre-paint inline
 * script in index.html (first paint without the /api/info round trip). */
export function readRememberedServerTheme(): ManifestTheme | null {
  try {
    const raw = localStorage.getItem(SERVER_THEME_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === 'object' && parsed !== null
      && typeof (parsed as ManifestTheme).slug === 'string'
      && SLUG_PATTERN.test((parsed as ManifestTheme).slug)
      && typeof (parsed as ManifestTheme).dark === 'boolean'
    ) {
      return parsed as ManifestTheme;
    }
  } catch {
    // Storage/JSON failures behave like "nothing remembered".
  }
  return null;
}

export function rememberServerTheme(theme: ManifestTheme): void {
  try {
    localStorage.setItem(SERVER_THEME_STORAGE_KEY, JSON.stringify(theme));
  } catch {
    // Storage may be unavailable; identity still applies for this session.
  }
}

function useExplicitThemePreference(): Theme | null {
  const { theme } = useTheme();
  // useTheme resolves stored -> system; a stored value always equals the
  // snapshot (system fallbacks only apply when nothing is stored), so this
  // comparison distinguishes explicit overrides from auto mode and stays
  // reactive to toggles through useSyncExternalStore.
  const stored = readStoredThemePreference();
  return stored !== null && stored === theme ? stored : null;
}

/**
 * Applies the resolved owner-theme identity to document.documentElement:
 * `data-am-theme="<slug>"` plus the mode class. Returns the identity so
 * AppAccentSync can decide whether theme_color stays the inline accent
 * fallback or must yield to the generated palette.
 */
export function useServerTheme(serverThemeName: string | null | undefined): ThemeIdentity {
  const explicitTheme = useExplicitThemePreference();
  const { theme } = useTheme();
  const identity = useMemo(
    // In auto mode `theme` already IS the system-preference fallback
    // (useTheme resolves stored -> media), so it doubles as `systemDark`
    // here; the explicit branches never read it. This avoids a second
    // matchMedia subscription (jsdom/old browsers ship none).
    () => resolveServerThemeIdentity({
      explicitTheme,
      serverThemeName,
      systemDark: theme === 'dark',
    }),
    [explicitTheme, theme, serverThemeName],
  );

  useEffect(() => {
    const root = document.documentElement;
    if (identity.slug) {
      root.setAttribute('data-am-theme', identity.slug);
    } else {
      root.removeAttribute('data-am-theme');
    }
    applyDocumentTheme(identity.mode);
  }, [identity]);

  useEffect(() => {
    const match = findThemeByName(serverThemeName);
    if (match) rememberServerTheme(match);
  }, [serverThemeName]);

  return identity;
}
