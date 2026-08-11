import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { AppHeader } from '../layout/AppHeader';
import { useI18n } from '../../hooks/useI18n';
import './Gallery.css';

interface GalleryLayoutProps {
  children: ReactNode;
  onOpenPalette?: () => void;
}

/** Gallery shell that preserves the current Header/AuthContext instead of replacing it. */
export function GalleryLayout({ children, onOpenPalette }: GalleryLayoutProps) {
  const location = useLocation();
  const { t } = useI18n();
  const contextPath = new URLSearchParams(location.search).get('path');
  const workspaceHref = contextPath ? `/browse?path=${encodeURIComponent(contextPath)}` : '/browse';

  return (
    <div className="gallery-shell">
      <AppHeader
        activeArea="gallery"
        workspaceHref={workspaceHref}
        contextNav={[
          { to: '/gallery/collection', label: t('gallery.nav_collections') },
          { to: '/gallery/favorites', label: t('gallery.nav_favorites') },
        ]}
        onOpenPalette={onOpenPalette}
      />
      <main className="gallery-main">{children}</main>
    </div>
  );
}
