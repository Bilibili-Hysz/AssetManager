import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { useFavorites } from '../hooks/useFavorites';
import { useInvalidation } from '../hooks/useInvalidation';
import { useI18n } from '../hooks/useI18n';
import type { GalleryEntry, GalleryHomeResponse } from '../types/api';

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
  const [data, setData] = useState<GalleryHomeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const requestGenerationRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const [viewMode, setViewMode] = useState<GalleryViewMode>(() => readHomeLatestView());
  const [failedFeaturedImageUrl, setFailedFeaturedImageUrl] = useState<string | null>(null);

  const reload = useCallback(() => setReloadKey(value => value + 1), []);
  useInvalidation(['files', 'home', 'metadata', 'tags'], () => reload());

  useEffect(() => {
    requestGenerationRef.current += 1;
    const requestGeneration = requestGenerationRef.current;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    galleryApi.home(controller.signal)
      .then(response => {
        if (requestGeneration !== requestGenerationRef.current) return;
        if ('building' in response && (response as { building?: boolean }).building) {
          // The backend builds the home projection in the background for
          // very large libraries; poll until it is ready.
          setBuilding(true);
          pollTimerRef.current = window.setTimeout(() => {
            if (requestGenerationRef.current === requestGeneration) reload();
          }, 5000);
          return;
        }
        setBuilding(false);
        setData(response as GalleryHomeResponse);
        setFailedFeaturedImageUrl(null);
      })
      .catch(err => {
        if (!controller.signal.aborted && requestGeneration === requestGenerationRef.current) {
          setError(err instanceof Error ? err.message : t('gallery.load_failed'));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && requestGeneration === requestGenerationRef.current) setLoading(false);
      });
    return () => {
      controller.abort();
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [galleryApi, reloadKey, t]);

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

        {loading && !building ? (
          <div className="gallery-skeleton-grid" role="status" aria-label={t('gallery.loading')}>
            {homeSkeletonKeys.map(key => <div key={key} className="gallery-skeleton-card" />)}
          </div>
        ) : building ? (
          <div className="gallery-error-state" role="status" aria-label={t('gallery.building')}>
            <h2>{t('gallery.building')}</h2>
            <p>{t('gallery.building_description')}</p>
          </div>
        ) : error ? (
          <div className="gallery-error-state">
            <h2>{t('gallery.unavailable')}</h2>
            <p>{error}</p>
            <div className="gallery-empty-actions">
              <button type="button" className="gallery-secondary-button" onClick={reload}><RefreshCw size={15} /> {t('gallery.retry')}</button>
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
