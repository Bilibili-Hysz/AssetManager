import { useState } from 'react';
import { ArrowLeft, SlidersHorizontal, Star, Wrench } from 'lucide-react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { GalleryCard } from '../components/gallery/GalleryCard';
import { GalleryEmptyState } from '../components/gallery/GalleryEmptyState';
import { GalleryLayout } from '../components/gallery/GalleryLayout';
import { GalleryTiledGrid } from '../components/gallery/GalleryTiledGrid';
import { GalleryViewControls, galleryMediaMode, type GalleryViewMode } from '../components/gallery/GalleryViewControls';
import { useGalleryApi } from '../hooks/usePageApis';
import { useCachedQuery } from '../hooks/useCachedQuery';
import { useFavorites } from '../hooks/useFavorites';
import { useI18n } from '../hooks/useI18n';
import type { GalleryCollectionResponse, GalleryEntry } from '../types/api';

type GalleryCollectionKind = 'all' | 'artwork';

type GallerySort = 'updated' | 'name';

function entryDetailUrl(entry: GalleryEntry, context: string) {
  return `/detail?path=${encodeURIComponent(entry.path)}&from=gallery&context=${encodeURIComponent(context)}`;
}

interface GalleryCollectionPageProps {
  onOpenPalette?: () => void;
}

export default function GalleryCollectionPage({ onOpenPalette }: GalleryCollectionPageProps) {
  const { isFavorite, toggleFavorite } = useFavorites();
  const galleryApi = useGalleryApi();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const path = searchParams.get('path') ?? '';
  const [kind, setKind] = useState<GalleryCollectionKind>('all');
  const [sort, setSort] = useState<GallerySort>('updated');
  const [viewMode, setViewMode] = useState<GalleryViewMode>('masonry');

  const { data, error, isLoading, refresh } = useCachedQuery<GalleryCollectionResponse>({
    key: ['gallery-collection', path, sort, kind],
    queryFn: signal => galleryApi.collection(path, { sort, kind }, signal),
    domains: ['files', 'home', 'metadata', 'tags'],
  });

  const loadFailed = error != null;
  const errorMessage = error instanceof Error ? error.message : t('gallery.load_failed');

  const collection = data?.collection;
  const children = data?.children ?? [];
  const entries = data?.entries ?? [];
  const changeViewMode = (nextMode: GalleryViewMode) => {
    setViewMode(nextMode);
    try { localStorage.setItem('am_gallery_view', nextMode); } catch { /* optional preference */ }
  };

  return (
    <GalleryLayout onOpenPalette={onOpenPalette}>
      <div className="gallery-page gallery-collection-page">
        <div className="gallery-breadcrumbs">
          <Link to="/gallery"><ArrowLeft size={15} /> {t('gallery.nav_home')}</Link>
          {path && <><span>/</span><span>{path.split('/').filter(Boolean).join(' / ')}</span></>}
        </div>

        {isLoading ? (
          <div className="gallery-skeleton-detail"><div /><div /><div /></div>
        ) : loadFailed || !collection ? (
          <GalleryEmptyState
            title={t('gallery.collection_unavailable')}
            description={loadFailed ? errorMessage : t('gallery.collection_missing')}
            onRetry={refresh}
          />
        ) : (
          <>
            <section className="gallery-collection-heading">
              <div>
                <span className="gallery-eyebrow">{collection.kind === 'project' ? t('gallery.project') : t('gallery.collection')}</span>
                <h1>{collection.name}</h1>
                <p>{collection.kind === 'project'
                  ? t('gallery.project_meta', collection.artwork_count ?? 0, collection.size_fmt ?? '0 B')
                  : t('gallery.collection_summary', collection.artwork_count ?? 0, collection.child_count ?? 0, collection.size_fmt ?? '0 B')}</p>
              </div>
              <div className="gallery-collection-actions">
                <button
                  type="button"
                  className="gallery-secondary-button"
                  onClick={() => toggleFavorite(collection.path)}
                  aria-pressed={isFavorite(collection.path)}
                  aria-label={isFavorite(collection.path)
                    ? t('gallery.remove_favorite', collection.name)
                    : t('gallery.add_favorite', collection.name)}
                  title={isFavorite(collection.path)
                    ? t('gallery.remove_favorite', collection.name)
                    : t('gallery.add_favorite', collection.name)}
                >
                  <Star size={15} fill={isFavorite(collection.path) ? 'currentColor' : 'none'} />
                  {isFavorite(collection.path) ? t('gallery.saved') : t('gallery.save_collection')}
                </button>
                <button type="button" className="gallery-secondary-button" onClick={() => navigate(`/browse?path=${encodeURIComponent(collection.path)}`)}>
                  <Wrench size={15} /> {t('gallery.workspace')}
                </button>
              </div>
            </section>

            <div className="gallery-filter-bar">
              <div className="gallery-filter-group">
                <SlidersHorizontal size={14} />
                {(['all', 'artwork'] as const).map(value => (
                  <button
                    key={value}
                    type="button"
                    className={kind === value ? 'gallery-filter-active' : ''}
                    aria-pressed={kind === value}
                    onClick={() => setKind(value)}
                  >
                    {value === 'all' ? t('gallery.all') : t('gallery.works')}
                  </button>
                ))}
              </div>
              <div className="gallery-filter-tools">
                <label className="gallery-sort-control">
                  {t('gallery.sort')}
                  <select value={sort} onChange={event => setSort(event.target.value as GallerySort)}>
                    <option value="updated">{t('gallery.latest')}</option>
                    <option value="name">{t('gallery.name')}</option>
                  </select>
                </label>
                <GalleryViewControls value={viewMode} onChange={changeViewMode} />
              </div>
            </div>

            {children.length > 0 && kind === 'all' && (
              <section className="gallery-section gallery-subsection">
                <div className="gallery-section-heading"><h2>{t('gallery.subcollections_projects')}</h2></div>
                <div className="gallery-card-grid gallery-collection-grid">
                  {children.map(entry => (
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
              </section>
            )}

            <section className="gallery-section gallery-subsection">
              <div className="gallery-section-heading">
                <h2>{t('gallery.works')}</h2>
                <span className="gallery-section-meta">{entries.length}</span>
              </div>
              {entries.length > 0 ? (
                viewMode === 'masonry' ? (
                  <GalleryTiledGrid entries={entries}>
                    {entry => (
                      <GalleryCard
                        key={entry.path}
                        entry={entry}
                        isFavorite={isFavorite(entry.path)}
                        onToggleFavorite={() => toggleFavorite(entry.path)}
                        onOpen={() => navigate(entryDetailUrl(entry, collection.path))}
                        onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(collection.path)}`)}
                      />
                    )}
                  </GalleryTiledGrid>
                ) : (
                  <div className={`gallery-work-grid gallery-view-${viewMode}`}>
                    {entries.map(entry => (
                      <GalleryCard
                        key={entry.path}
                        entry={entry}
                        isFavorite={isFavorite(entry.path)}
                        onToggleFavorite={() => toggleFavorite(entry.path)}
                        mediaMode={galleryMediaMode(viewMode)}
                        onOpen={() => navigate(entryDetailUrl(entry, collection.path))}
                        onWorkspace={() => navigate(`/browse?path=${encodeURIComponent(collection.path)}`)}
                      />
                    ))}
                  </div>
                )
              ) : <p className="gallery-muted-copy">{t('gallery.no_direct_works')}</p>}
            </section>
          </>
        )}
      </div>
    </GalleryLayout>
  );
}
