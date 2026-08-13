import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, RefreshCw, Wrench } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { createGalleryApi } from '../api/gallery';
import { GalleryCard } from '../components/gallery/GalleryCard';
import { GalleryEmptyState } from '../components/gallery/GalleryEmptyState';
import { GalleryLayout } from '../components/gallery/GalleryLayout';
import { GallerySection } from '../components/gallery/GallerySection';
import { GalleryTiledGrid } from '../components/gallery/GalleryTiledGrid';
import { GalleryViewControls, galleryMediaMode, type GalleryViewMode } from '../components/gallery/GalleryViewControls';
import { useAuth } from '../hooks/useAuth';
import { useCachedQuery } from '../hooks/useCachedQuery';
import { useFavorites } from '../hooks/useFavorites';
import { useI18n } from '../hooks/useI18n';
import type { GalleryEntry, GalleryHomeResponse } from '../types/api';

/**
 * The backend reports `building` on the home projection while it assembles
 * the response for very large libraries; it is not part of the public type.
 */
type GalleryHomeQueryResponse = GalleryHomeResponse & { building?: boolean };

const homeSkeletonKeys = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight'];
const homeLatestViewStorageKey = 'am_gallery_home_latest_view';

function readHomeLatestView(): GalleryViewMode {
  try {
    const value = localStorage.getItem(homeLatestViewStorageKey);
    if (value === 'masonry' || value === 'grid' || value === 'compact') return value;
  } catch { /* localStorage is optional */ }
  return 'masonry';
}

function entryDetailUrl(entry: GalleryEntry) {
  const context = entry.parent_path || '';
  return `/detail?path=${encodeURIComponent(entry.path)}&from=gallery&context=${encodeURIComponent(context)}`;
}

interface GalleryHomePageProps {
  onOpenPalette?: () => void;
}

export default function GalleryHomePage({ onOpenPalette }: GalleryHomePageProps) {
  const { api } = useAuth();
  const { isFavorite, toggleFavorite } = useFavorites();
  const galleryApi = useMemo(() => createGalleryApi(api), [api]);
  const { t } = useI18n();
  const navigate = useNavigate();
  const [viewMode, setViewMode] = useState<GalleryViewMode>(() => readHomeLatestView());
  const [failedFeaturedImageUrl, setFailedFeaturedImageUrl] = useState<string | null>(null);

  const { data, error, isLoading, refresh } = useCachedQuery<GalleryHomeQueryResponse>({
    key: ['gallery-home'],
    queryFn: signal => galleryApi.home(signal) as Promise<GalleryHomeQueryResponse>,
    domains: ['files', 'home', 'metadata', 'tags'],
  });

  const building = data?.building ?? false;
  const loadFailed = error != null;
  const errorMessage = error instanceof Error ? error.message : t('gallery.load_failed');

  // The backend builds the home projection in the background for very large
  // libraries; poll until it is ready. Each building response re-arms the
  // timer, so a library that stays in `building` keeps polling every 5s like
  // the pre-cache flow.
  useEffect(() => {
    if (!building) return;
    const timer = setTimeout(() => { refresh(); }, 5000);
    return () => clearTimeout(timer);
  }, [building, data, refresh]);

  // A fresh response may reference a new cover; retry the failed image.
  useEffect(() => {
    if (data && !data.building) setFailedFeaturedImageUrl(null);
  }, [data]);

  const featured = data?.featured;
  const collections = data?.collections ?? [];
  const projects = data?.projects ?? [];
  const recent = data?.recent ?? [];
  const featuredLabel = featured?.kind === 'project' ? t('gallery.latest_project') : t('gallery.latest_collection');
  const featuredAction = featured?.kind === 'project' ? t('gallery.open_project') : t('gallery.open_collection');

  const changeViewMode = (nextMode: GalleryViewMode) => {
    setViewMode(nextMode);
    try { localStorage.setItem(homeLatestViewStorageKey, nextMode); } catch { /* optional preference */ }
  };

  return (
    <GalleryLayout onOpenPalette={onOpenPalette}>
      <div className="gallery-page gallery-home-page">
        <section className="gallery-hero">
          {featured?.cover_url && featured.cover_url !== failedFeaturedImageUrl ? (
            <img
              src={featured.cover_url}
              alt=""
              className="gallery-hero-image"
              draggable={false}
              onError={() => setFailedFeaturedImageUrl(featured.cover_url ?? null)}
            />
          ) : <div className="gallery-hero-placeholder" />}
          <div className="gallery-hero-overlay" />
          <div className="gallery-hero-content">
            <span className="gallery-eyebrow">{featuredLabel}</span>
            <h1>{featured?.name ?? t('gallery.visual_library')}</h1>
            <p>{featured ? t('gallery.works_to_explore', featured.artwork_count ?? 0) : t('gallery.visual_library_description')}</p>
            {featured && (
              <div className="gallery-hero-actions">
                <button
                  type="button"
                  className="gallery-primary-button"
                  onClick={() => navigate(`/gallery/collection?path=${encodeURIComponent(featured.path)}`)}
                >
                  {featuredAction} <ArrowRight size={16} />
                </button>
                <button type="button" className="gallery-secondary-button" onClick={() => navigate(`/browse?path=${encodeURIComponent(featured.path)}`)}>
                  <Wrench size={15} /> {t('gallery.open_workspace_action')}
                </button>
                <button
                  type="button"
                  className="gallery-hero-favorite"
                  aria-pressed={isFavorite(featured.path)}
                  onClick={() => toggleFavorite(featured.path)}
                >
                  {isFavorite(featured.path) ? t('gallery.saved') : featured.kind === 'project' ? t('gallery.save_project') : t('gallery.save_collection')}
                </button>
              </div>
            )}
          </div>
        </section>

        {isLoading && !building ? (
          <div className="gallery-skeleton-grid" role="status" aria-label={t('gallery.loading')}>
            {homeSkeletonKeys.map(key => <div key={key} className="gallery-skeleton-card" />)}
          </div>
        ) : building ? (
          <div className="gallery-error-state" role="status" aria-label={t('gallery.building')}>
            <h2>{t('gallery.building')}</h2>
            <p>{t('gallery.building_description')}</p>
          </div>
        ) : loadFailed ? (
          <div className="gallery-error-state">
            <h2>{t('gallery.unavailable')}</h2>
            <p>{errorMessage}</p>
            <div className="gallery-empty-actions">
              <button type="button" className="gallery-secondary-button" onClick={refresh}><RefreshCw size={15} /> {t('gallery.retry')}</button>
              <Link to="/browse" className="gallery-secondary-button"><Wrench size={15} /> {t('gallery.open_workspace_action')}</Link>
            </div>
          </div>
        ) : collections.length === 0 && projects.length === 0 && recent.length === 0 ? (
          <GalleryEmptyState title={t('gallery.no_visual_assets')} description={t('gallery.inspect_workspace')} />
        ) : (
          <>
            {collections.length > 0 && (
              <GallerySection
                title={t('gallery.collections')}
                action={<Link to="/gallery/collection" className="gallery-section-link">{t('gallery.view_all')} <ArrowRight size={14} /></Link>}
              >
                <div className="gallery-card-grid gallery-collection-grid">
                  {collections.map(entry => (
                    <GalleryCard
                      key={entry.path}
                      entry={entry}
                      isFavorite={isFavorite(entry.path)}
                      onToggleFavorite={() => toggleFavorite(entry.path)}
                      onOpen={() => navigate(`/gallery/collection?path=${encodeURIComponent(entry.path)}`)}
                      onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(entry.path)}`)}
                    />
                  ))}
                </div>
              </GallerySection>
            )}
            {projects.length > 0 && (
              <GallerySection title={t('gallery.projects')}>
                <div className="gallery-card-grid gallery-collection-grid">
                  {projects.map(entry => (
                    <GalleryCard
                      key={entry.path}
                      entry={entry}
                      isFavorite={isFavorite(entry.path)}
                      onToggleFavorite={() => toggleFavorite(entry.path)}
                      onOpen={() => navigate(`/gallery/collection?path=${encodeURIComponent(entry.path)}`)}
                      onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(entry.path)}`)}
                    />
                  ))}
                </div>
              </GallerySection>
            )}
            <GallerySection
              title={t('gallery.latest_works')}
              action={
                <div className="gallery-section-tools">
                  <span className="gallery-section-meta">{t('gallery.total_works', data?.stats.artworks ?? 0)}</span>
                  <GalleryViewControls value={viewMode} onChange={changeViewMode} />
                </div>
              }
            >
              {recent.length > 0 ? (
                viewMode === 'masonry' ? (
                  <GalleryTiledGrid entries={recent}>
                    {entry => (
                      <GalleryCard
                        key={entry.path}
                        entry={entry}
                        isFavorite={isFavorite(entry.path)}
                        onToggleFavorite={() => toggleFavorite(entry.path)}
                        onOpen={() => navigate(entryDetailUrl(entry))}
                        onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(entry.parent_path || '')}`)}
                      />
                    )}
                  </GalleryTiledGrid>
                ) : (
                  <div className={`gallery-work-grid gallery-view-${viewMode}`}>
                    {recent.map(entry => (
                      <GalleryCard
                        key={entry.path}
                        entry={entry}
                        isFavorite={isFavorite(entry.path)}
                        onToggleFavorite={() => toggleFavorite(entry.path)}
                        mediaMode={galleryMediaMode(viewMode)}
                        onOpen={() => navigate(entryDetailUrl(entry))}
                        onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(entry.parent_path || '')}`)}
                      />
                    ))}
                  </div>
                )
              ) : <p className="gallery-muted-copy">{t('gallery.no_root_works')}</p>}
            </GallerySection>
          </>
        )}
      </div>
    </GalleryLayout>
  );
}
