import { useState } from 'react';
import { Download, Eye, File, Folder, FolderOpen, Star } from 'lucide-react';
import type { BrowsableItem } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';

interface MasonryViewProps {
  items: BrowsableItem[];
  selected?: Set<string>;
  selectionMode?: boolean;
  onSelect?: (path: string) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  getThumbnail?: (path: string) => string | undefined;
  onContextMenu?: (e: React.MouseEvent, item: BrowsableItem) => void;
  onTagClick?: (tag: string) => void;
  onDoubleClick?: (item: BrowsableItem) => void;
  onDownload?: (item: BrowsableItem) => void;
  onToggleFavorite?: (path: string) => void;
  isFavorite?: (path: string) => boolean;
  isMobile?: boolean;
}

function MasonryItem({
  item,
  selected,
  selectionMode,
  onSelect,
  onInspect,
  onNavigate,
  getThumbnail,
  onContextMenu,
  onTagClick,
  onToggleFavorite,
  isFavorite,
  onDoubleClick,
  onDownload,
  isMobile,
}: {
  item: BrowsableItem;
  selected?: boolean;
  selectionMode?: boolean;
  onSelect?: (path: string) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  getThumbnail?: (path: string) => string | undefined;
  onContextMenu?: (e: React.MouseEvent, item: BrowsableItem) => void;
  onTagClick?: (tag: string) => void;
  onToggleFavorite?: (path: string) => void;
  isFavorite?: (path: string) => boolean;
  onDoubleClick?: (item: BrowsableItem) => void;
  onDownload?: (item: BrowsableItem) => void;
  isMobile?: boolean;
}) {
  const { t } = useI18n();
  const [failedThumb, setFailedThumb] = useState<string | null>(null);
  const [hover, setHover] = useState(false);
  const isDir = item.type === 'dir';
  const thumb = getThumbnail?.(item.path) ?? item.thumbnail_url;
  const showImage = Boolean(thumb) && failedThumb !== thumb && !isDir;
  const fav = isFavorite?.(item.path) ?? false;
  const canFavorite = isDir || item.category === 'image';

  const handlePrimaryClick = () => {
    if (selectionMode) {
      onSelect?.(item.path);
      return;
    }
    if (isMobile && isDir) onNavigate?.(item.path);
    else onInspect?.(item);
  };

  const handlePrimaryOpen = () => {
    if (selectionMode) return;
    if (onDoubleClick) onDoubleClick(item);
    else if (isDir) onNavigate?.(item.path);
    else onInspect?.(item);
  };

  return (
    <div
      style={{
        breakInside: 'avoid',
        marginBottom: '12px',
        borderRadius: '8px',
        border: `1px solid ${selected ? 'var(--color-accent)' : hover ? 'var(--color-border-strong)' : 'var(--color-border)'}`,
        background: selected ? 'var(--color-accent-subtle)' : hover ? 'var(--color-surface-hover)' : 'var(--color-surface)',
        transition: 'border-color 200ms, background 200ms, transform 200ms, box-shadow 200ms',
        transform: hover ? 'translateY(-2px)' : 'none',
        boxShadow: hover ? '0 8px 24px rgba(0,0,0,0.15)' : 'none',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        aria-label={item.size_fmt ? `${item.name}, ${item.size_fmt}` : item.name}
        onClick={handlePrimaryClick}
        onDoubleClick={event => { event.preventDefault(); handlePrimaryOpen(); }}
        onContextMenu={e => onContextMenu?.(e, item)}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{ display: 'block', width: '100%', padding: 0, border: 0, background: 'transparent', color: 'inherit', textAlign: 'left', cursor: 'pointer' }}
      >
        <div style={{ position: 'relative', width: '100%', aspectRatio: isDir ? '4/3' : undefined, background: 'var(--color-surface-hover)' }}>
          {showImage ? (
            <img
              src={thumb}
              alt={item.name}
              loading="lazy"
              draggable={false}
              onError={() => setFailedThumb(thumb ?? null)}
              style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '120px', gap: '6px' }}>
              {isDir ? <Folder size={32} style={{ color: '#f59e0b' }} /> : <File size={32} style={{ color: '#64748b' }} />}
            </div>
          )}
        </div>
        <div style={{ padding: '8px 10px' }}>
          <p style={{ margin: 0, fontSize: '12px', fontWeight: 500, color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.name}
          </p>
          {item.size_fmt && <p style={{ margin: '2px 0 0', fontSize: '11px', color: 'var(--color-text-muted)' }}>{item.size_fmt}</p>}
        </div>
      </button>

      {selectionMode && (
        <button
          type="button"
          aria-label={t('action.select') + ': ' + item.name}
          aria-pressed={Boolean(selected)}
          onClick={event => { event.stopPropagation(); onSelect?.(item.path); }}
          style={{ position: 'absolute', top: '8px', left: '8px', width: '20px', height: '20px', borderRadius: '4px', border: `2px solid ${selected ? 'var(--color-accent)' : 'rgba(255,255,255,0.5)'}`, background: selected ? 'var(--color-accent)' : 'rgba(0,0,0,0.4)', color: selected ? 'white' : 'transparent', display: 'grid', placeItems: 'center', cursor: 'pointer', fontSize: '11px', fontWeight: 700, transition: 'border-color 150ms, background 150ms' }}
        >
          <span aria-hidden="true">✓</span>
        </button>
      )}

      {onToggleFavorite && canFavorite && (
        <button
          type="button"
          className="masonry-fav-button"
          aria-label={fav ? t('gallery.remove_favorite', item.name) : t('gallery.add_favorite', item.name)}
          aria-pressed={fav}
          onClick={event => { event.stopPropagation(); onToggleFavorite(item.path); }}
          style={{ position: 'absolute', top: '8px', right: '8px', width: '24px', height: '24px', borderRadius: '4px', border: 'none', background: 'rgba(0,0,0,0.3)', color: fav ? '#fbbf24' : 'rgba(255,255,255,0.6)', display: 'grid', placeItems: 'center', cursor: 'pointer', opacity: hover || fav ? 1 : 0, transition: 'opacity 150ms, color 150ms' }}
        >
          <Star size={14} fill={fav ? '#fbbf24' : 'none'} />
        </button>
      )}

      {item.tags && item.tags.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', padding: '0 10px 8px' }}>
        {item.tags.slice(0, 3).map(tag => <button key={tag} type="button" onClick={event => { event.stopPropagation(); onTagClick?.(tag); }} style={{ border: '1px solid var(--color-accent-border)', borderRadius: '999px', padding: '2px 6px', background: 'var(--color-accent-subtle)', color: 'var(--color-accent)', fontSize: '10px' }}>{tag}</button>)}
        {item.tags.length > 3 && <span style={{ padding: '2px 6px', color: 'var(--color-text-muted)', fontSize: '10px' }}>+{item.tags.length - 3}</span>}
      </div>}

      {(onInspect || onDoubleClick || onDownload) && <div style={{ display: 'flex', gap: '4px', margin: '0 10px 10px', paddingTop: '7px', borderTop: '1px solid var(--color-border)' }}>
        {onInspect && <button type="button" onClick={event => { event.stopPropagation(); onInspect(item); }} aria-label={t('action.detail') + ': ' + item.name} title={t('action.inspect', item.name)} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px', flex: 1, minWidth: 0, padding: '4px 5px', border: 0, borderRadius: '4px', background: 'transparent', color: 'var(--color-text-secondary)', fontSize: '10px', cursor: 'pointer' }}><Eye size={12} aria-hidden="true" /><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('action.detail')}</span></button>}
        {onDoubleClick && <button type="button" onClick={event => { event.stopPropagation(); onDoubleClick(item); }} aria-label={isDir ? t('action.open') + ': ' + item.name : t('action.open') + ': ' + item.name} title={isDir ? t('action.open_folder', item.name) : t('action.open_item', item.name)} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px', flex: 1, minWidth: 0, padding: '4px 5px', border: 0, borderRadius: '4px', background: 'transparent', color: 'var(--color-accent-hover)', fontSize: '10px', cursor: 'pointer' }}><FolderOpen size={12} aria-hidden="true" /><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('action.open')}</span></button>}
        {onDownload && <button type="button" onClick={event => { event.stopPropagation(); onDownload(item); }} aria-label={isDir ? t('action.download') + ': ' + item.name : t('action.download') + ': ' + item.name} title={isDir ? t('action.download_folder') : t('action.download_file')} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px', flex: 1, minWidth: 0, padding: '4px 5px', border: 0, borderRadius: '4px', background: 'transparent', color: 'var(--color-success)', fontSize: '10px', cursor: 'pointer' }}><Download size={12} aria-hidden="true" /><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('action.download')}</span></button>}
      </div>}
    </div>
  );
}

export function MasonryView({
  items, selected, selectionMode, onSelect, onInspect, onNavigate,
  getThumbnail, onContextMenu, onTagClick, onDoubleClick,
  onDownload, isMobile,
  onToggleFavorite, isFavorite,
}: MasonryViewProps) {
  return (
    <div
      data-testid="masonry-view"
      style={{
        columnGap: '12px',
        padding: '16px',
      }}
      className="masonry-responsive"
    >
      {items.map(item => (
        <MasonryItem
          key={item.path}
          item={item}
          selected={selected?.has(item.path)}
          selectionMode={selectionMode}
          onSelect={onSelect}
          onInspect={onInspect}
          onNavigate={onNavigate}
          getThumbnail={getThumbnail}
          onContextMenu={onContextMenu}
           onTagClick={onTagClick}
           onDoubleClick={onDoubleClick}
           onDownload={onDownload}
           isMobile={isMobile}
          onToggleFavorite={onToggleFavorite}
          isFavorite={isFavorite}
        />
      ))}
      <style>{`
        .masonry-responsive { column-count: 4; }
        @media (max-width: 1400px) { .masonry-responsive { column-count: 3; } }
        @media (max-width: 1000px) { .masonry-responsive { column-count: 2; } }
        @media (max-width: 600px) { .masonry-responsive { column-count: 1; } }
        /* D8: keep the favorite toggle reachable for keyboard users even before hover. */
        .masonry-fav-button:focus-visible { opacity: 1 !important; outline: 2px solid var(--color-accent); outline-offset: -2px; }
      `}</style>
    </div>
  );
}
