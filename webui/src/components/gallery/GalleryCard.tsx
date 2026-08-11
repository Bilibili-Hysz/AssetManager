import { memo, useState } from 'react';
import { Download, FolderOpen, ImageOff, Star, Wrench } from 'lucide-react';
import type { GalleryEntry } from '../../types/api';
import { useAuth } from '../../hooks/useAuth';
import { useQuota } from '../../hooks/useQuota';
import { useI18n } from '../../hooks/useI18n';
import type { GalleryMediaMode } from './GalleryViewControls';

interface GalleryCardProps {
  entry: GalleryEntry;
  onOpen: () => void;
  onWorkspace?: () => void;
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
  mediaMode?: GalleryMediaMode;
}

/**
 * A compact visual-library card adapted to the current AuthContext and download contract.
 *
 * D4: `useQuota` is per-instance state (no module-level cache), so every card that mounts
 * fires its own `getQuota` request. `React.memo` prevents needless re-renders/re-mounts
 * when the parent re-renders — but only when the props are referentially stable. Callers
 * that pass inline arrow functions (e.g. `onOpen={() => navigate(...)}`) still defeat the
 * memo; keep those callbacks memoized (useCallback) in the parent for the memo to pay off.
 */
export const GalleryCard = memo(function GalleryCard({
  entry,
  onOpen,
  onWorkspace,
  isFavorite = false,
  onToggleFavorite,
  mediaMode = 'square',
}: GalleryCardProps) {
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);
  const { api, capabilities } = useAuth();
  const { t } = useI18n();
  const { guardDownload, refresh: refreshQuota } = useQuota();
  const isArtwork = entry.kind === 'artwork';
  const imageUrl = entry.cover_url ?? entry.thumbnail_url;
  const naturalAspectRatio = entry.aspect_ratio && entry.aspect_ratio > 0 ? entry.aspect_ratio : 4 / 3;
  const mediaAspectRatio = mediaMode === 'uniform'
    ? '4 / 3'
    : mediaMode === 'square'
      ? '1 / 1'
      : mediaMode === 'compact' || !isArtwork
        ? '16 / 10'
        : `${Math.min(1.85, Math.max(0.62, naturalAspectRatio))}`;

  const download = () => {
    void (async () => {
      if (!await guardDownload()) return;
      window.open(api.buildUrl(`download/${encodeURIComponent(entry.path)}`), '_blank', 'noopener,noreferrer');
      void refreshQuota();
    })();
  };

  return (
    <article className={`gallery-card gallery-card-${entry.kind}`}>
      <div className="gallery-card-media-shell">
        <button type="button" className="gallery-card-media" onClick={onOpen} aria-label={t('gallery.open_entry', entry.name)}>
          {imageUrl && imageUrl !== failedImageUrl ? (
            <img
              src={imageUrl}
              alt={entry.name}
              loading="lazy"
              draggable={false}
              onError={() => setFailedImageUrl(imageUrl)}
              style={{ aspectRatio: mediaAspectRatio, objectFit: 'cover' }}
            />
          ) : (
            <span className="gallery-card-placeholder" style={{ aspectRatio: mediaAspectRatio }}>
              {isArtwork ? <ImageOff size={34} /> : <FolderOpen size={42} />}
            </span>
          )}
        </button>
        {onToggleFavorite && (
          <button
            type="button"
            className={`gallery-card-fav ${isFavorite ? 'gallery-card-fav-active' : ''}`}
            onClick={(event) => {
              event.stopPropagation();
              onToggleFavorite();
            }}
            aria-label={isFavorite ? t('gallery.remove_favorite', entry.name) : t('gallery.add_favorite', entry.name)}
            title={isFavorite ? t('gallery.remove_favorite', entry.name) : t('gallery.add_favorite', entry.name)}
            aria-pressed={isFavorite}
          >
            <Star size={15} fill={isFavorite ? 'currentColor' : 'none'} aria-hidden="true" />
          </button>
        )}
        {(onWorkspace || capabilities.download) && (
          <div className="gallery-card-hover-actions">
            {capabilities.download && (
              <button
                type="button"
                className="gallery-card-hover-action"
                onClick={download}
                aria-label={t('gallery.download_entry', entry.name)}
                title={t('gallery.download_entry', entry.name)}
              >
                <Download size={14} />
              </button>
            )}
            {onWorkspace && (
              <button
                type="button"
                className="gallery-card-hover-action"
                onClick={onWorkspace}
                aria-label={t('gallery.open_workspace', entry.name)}
                title={t('gallery.workspace')}
              >
                <Wrench size={14} />
              </button>
            )}
          </div>
        )}
      </div>
      <div className="gallery-card-body">
        <div className="gallery-card-copy">
          <h3 title={entry.name}>{entry.name}</h3>
          <p>
            {entry.kind === 'collection'
              ? t('gallery.collection_meta', entry.child_count ?? 0, entry.artwork_count ?? 0)
              : entry.kind === 'project'
                ? t('gallery.project_meta', entry.artwork_count ?? 0, entry.size_fmt ?? t('gallery.project'))
                : entry.parent_path || t('gallery.library')}
          </p>
        </div>
      </div>
    </article>
  );
});
