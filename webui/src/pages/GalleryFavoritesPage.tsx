import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GalleryCard } from '../components/gallery/GalleryCard';
import { GalleryEmptyState } from '../components/gallery/GalleryEmptyState';
import { GalleryLayout } from '../components/gallery/GalleryLayout';
import { GalleryTiledGrid } from '../components/gallery/GalleryTiledGrid';
import { GalleryViewControls, galleryMediaMode, readGalleryView, type GalleryViewMode } from '../components/gallery/GalleryViewControls';
import { useFavorites } from '../hooks/useFavorites';
import { useI18n } from '../hooks/useI18n';

const favoritesSkeletonKeys = ['one', 'two', 'three', 'four', 'five', 'six'];

function openEntryUrl(path: string, kind: 'collection' | 'project' | 'artwork', parentPath: string | null) {
  if (kind === 'collection' || kind === 'project') {
    return `/gallery/collection?path=${encodeURIComponent(path)}`;
  }
  return `/detail?path=${encodeURIComponent(path)}&from=gallery&context=${encodeURIComponent(parentPath ?? '')}`;
}

interface GalleryFavoritesPageProps {
  onOpenPalette?: () => void;
}

export default function GalleryFavoritesPage({ onOpenPalette }: GalleryFavoritesPageProps) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { items, loading, error, isFavorite, toggleFavorite, refresh } = useFavorites();
  const [viewMode, setViewMode] = useState<GalleryViewMode>(() => readGalleryView());

  const changeViewMode = (nextMode: GalleryViewMode) => {
    setViewMode(nextMode);
    try {
      localStorage.setItem('am_gallery_view', nextMode);
    } catch {
      // View preference is optional.
    }
  };

  return (
    <GalleryLayout onOpenPalette={onOpenPalette}>
      <div className="gallery-page gallery-favorites-page">
        <div className="gallery-page-heading">
          <div>
            <span className="gallery-eyebrow">{t('gallery.library')}</span>
            <h1>{t('gallery.nav_favorites')}</h1>
            <p>{t('gallery.favorites_description')}</p>
          </div>
          <span className="gallery-count-badge">{items.length}</span>
        </div>

        {loading ? (
          <div className="gallery-skeleton-grid" role="status" aria-label={t('gallery.loading')}>
            {favoritesSkeletonKeys.map(key => <div key={key} className="gallery-skeleton-card" />)}
          </div>
        ) : error ? (
          <GalleryEmptyState
            title={t('gallery.favorites_unavailable')}
            description={error}
            onRetry={() => { void refresh(); }}
          />
        ) : items.length === 0 ? (
          <GalleryEmptyState
            title={t('gallery.no_favorites')}
            description={t('gallery.save_hint')}
          />
        ) : (
          <>
            <div className="gallery-favorites-toolbar">
              <span className="gallery-section-meta">{items.length}</span>
              <GalleryViewControls value={viewMode} onChange={changeViewMode} />
            </div>
            {viewMode === 'masonry' ? (
              <GalleryTiledGrid entries={items}>
                {entry => (
                  <GalleryCard
                    key={entry.path}
                    entry={entry}
                    isFavorite={isFavorite(entry.path)}
                    onToggleFavorite={() => toggleFavorite(entry.path)}
                    onOpen={() => navigate(openEntryUrl(entry.path, entry.kind, entry.parent_path))}
                    onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(entry.parent_path || entry.path)}`)}
                  />
                )}
              </GalleryTiledGrid>
            ) : (
              <div className={`gallery-work-grid gallery-view-${viewMode}`}>
                {items.map(entry => (
                  <GalleryCard
                    key={entry.path}
                    entry={entry}
                    isFavorite={isFavorite(entry.path)}
                    onToggleFavorite={() => toggleFavorite(entry.path)}
                    mediaMode={galleryMediaMode(viewMode)}
                    onOpen={() => navigate(openEntryUrl(entry.path, entry.kind, entry.parent_path))}
                    onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(entry.parent_path || entry.path)}`)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </GalleryLayout>
  );
}
