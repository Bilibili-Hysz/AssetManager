import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './stores/AuthContext';
import { QueryCacheProvider } from './cache/QueryCacheContext';
import { RealtimeProvider } from './stores/RealtimeContext';
import { ToastProvider } from './components/ui/Toast';
import { DownloadProgressProvider } from './components/ui/DownloadProgress';
import { useApiDegradationToast } from './hooks/useApiDegradationToast';
import { useServerTheme } from './hooks/useServerTheme';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
const BrowsePage = lazy(() => import('./pages/BrowsePage'));
const DetailPage = lazy(() => import('./pages/DetailPage'));
const GalleryHomePage = lazy(() => import('./pages/GalleryHomePage'));
const GalleryCollectionPage = lazy(() => import('./pages/GalleryCollectionPage'));
const GalleryFavoritesPage = lazy(() => import('./pages/GalleryFavoritesPage'));
const ShareReceivePage = lazy(() => import('./pages/ShareReceivePage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
import ProtectedRoute from './components/auth/ProtectedRoute';
import { CommandPalette } from './components/ui/CommandPalette';
import { ShortcutsDialog } from './components/ui/ShortcutsDialog';
import { useAuthContext } from './stores/AuthContext';

/**
 * Bridges the ApiClient's throttled 429/503 degradation events to the global
 * toast. Mounted exactly once inside <ToastProvider>; the bus itself caps
 * notifications at one per kind per 10s, so bursts never stack toasts.
 */
function ApiDegradationToasts() {
  useApiDegradationToast();
  return null;
}

/**
 * Applies the follow-the-owner theme identity and the server-declared accent
 * color once /api/info is known. Lives *inside* AuthProvider (App itself is
 * outside it and must not call useAuthContext — createContext(null) would
 * throw).
 *
 * Coordination: with a matched owner theme (data-am-theme set) the generated
 * palette block owns --color-accent, so the inline theme_color override is
 * removed — inline styles outrank every stylesheet rule and would otherwise
 * flatten the owner palette. theme_color stays the accent fallback whenever
 * no identity block applies (unknown/absent theme_name, or the visitor's
 * explicit light/dark toggle leaving the owner theme's mode).
 */
function AppAccentSync() {
  const { serverInfo } = useAuthContext();
  const identity = useServerTheme(serverInfo?.theme_name ?? null);
  useEffect(() => {
    const accent = serverInfo?.theme_color;
    const root = document.documentElement;
    if (identity.slug) {
      root.style.removeProperty('--color-accent');
      root.style.removeProperty('--color-accent-hover');
      return;
    }
    if (!accent) return;
    root.style.setProperty('--color-accent', accent);
    root.style.setProperty('--color-accent-hover', accent);
  }, [serverInfo?.theme_color, identity.slug]);
  return null;
}

function App() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const openShortcuts = useCallback(() => {
    setPaletteOpen(false);
    setShortcutsOpen(true);
  }, []);
  const handlePaletteShortcut = useCallback((event: KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      setPaletteOpen(previous => !previous);
    }
  }, []);

  useEffect(() => {
    document.addEventListener('keydown', handlePaletteShortcut);
    return () => document.removeEventListener('keydown', handlePaletteShortcut);
  }, [handlePaletteShortcut]);

  // `?` (shift + /) toggles the shortcut cheat sheet (A3). Editable targets
  // are excluded so typing "?"/"？" into any field never opens it.
  const handleShortcutsShortcut = useCallback((event: KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key !== '?' && event.key !== '？') return;
    const target = event.target;
    const isEditable = target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || (target instanceof HTMLElement && target.isContentEditable);
    if (isEditable) return;
    event.preventDefault();
    setShortcutsOpen(previous => !previous);
  }, []);

  useEffect(() => {
    document.addEventListener('keydown', handleShortcutsShortcut);
    return () => document.removeEventListener('keydown', handleShortcutsShortcut);
  }, [handleShortcutsShortcut]);

  return (
    <BrowserRouter>
      <AuthProvider>
        <AppAccentSync />
        <RealtimeProvider>
          <QueryCacheProvider>
          <ToastProvider>
            <ApiDegradationToasts />
            <DownloadProgressProvider>
              <Suspense fallback={<div className="app-route-loading" role="status" aria-busy="true" />}>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route element={<ProtectedRoute capability="browse" />}>
                  <Route path="/browse" element={<BrowsePage onOpenPalette={openPalette} />} />
                  <Route path="/detail" element={<DetailPage onOpenPalette={openPalette} />} />
                  <Route path="/gallery" element={<GalleryHomePage onOpenPalette={openPalette} />} />
                  <Route path="/gallery/collection" element={<GalleryCollectionPage onOpenPalette={openPalette} />} />
                  <Route path="/gallery/favorites" element={<GalleryFavoritesPage onOpenPalette={openPalette} />} />
                </Route>
                <Route element={<ProtectedRoute capability="manage_users" />}>
                  <Route path="/admin" element={<AdminPage />} />
                </Route>
                <Route path="/s/:shareId" element={<ShareReceivePage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
              </Suspense>
              {paletteOpen && <CommandPalette open={true} onClose={() => setPaletteOpen(false)} onOpenShortcuts={openShortcuts} />}
              {shortcutsOpen && <ShortcutsDialog open={true} onClose={() => setShortcutsOpen(false)} />}
            </DownloadProgressProvider>
          </ToastProvider>
          </QueryCacheProvider>
        </RealtimeProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
