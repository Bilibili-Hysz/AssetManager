import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal, Download, Eye, FolderOpen, Link2 } from 'lucide-react';
import type { BrowsableItem } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { LayeredPreview } from './LayeredPreview';

export const SINGLE_CLICK_DELAY_MS = 300;

interface ProjectCardProps {
  item: BrowsableItem;
  selected?: boolean;
  selectionMode?: boolean;
  onSelect?: (value: string | BrowsableItem) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  isMobile?: boolean;
  onZipSelect?: () => void;
  onOpen?: () => void;
  onDownload?: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  thumbnail?: string;
  onTagClick?: (tag: string) => void;
  onCopyLink?: (path: string) => void;
}

export function ProjectCard({
  item,
  selected,
  selectionMode = false,
  onSelect,
  onInspect,
  onNavigate,
  isMobile = false,
  onZipSelect,
  onOpen,
  onDownload,
  onContextMenu,
  thumbnail,
  onTagClick,
  onCopyLink,
}: ProjectCardProps) {
  const { t } = useI18n();
  const zipSelect = onZipSelect ?? (() => onSelect?.(item));
  const [hover, setHover] = useState(false);
  const inspectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isDir = item.type === 'dir';

  const clearInspectTimer = () => {
    if (inspectTimer.current !== null) {
      clearTimeout(inspectTimer.current);
      inspectTimer.current = null;
    }
  };

  useEffect(() => clearInspectTimer, []);

  // Dynamic border and background based on state
  const cardStyle = {
    borderColor: selected ? 'var(--color-accent)' : hover ? 'var(--color-border-strong)' : 'var(--color-border)',
    backgroundColor: selected ? 'var(--color-accent-subtle)' : hover ? 'var(--color-surface-hover)' : 'var(--color-surface)',
  };

  return (
    <div
      className="relative rounded-lg transition-all duration-200 cursor-pointer group"
      style={{
        ...cardStyle,
        borderWidth: '1px',
        borderStyle: 'solid',
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onContextMenu={onContextMenu}
    >
      <button
        type="button"
        className="block w-full text-left rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset"
        style={{ '--tw-ring-color': 'var(--color-accent)' } as React.CSSProperties}
        aria-label={item.size_fmt ? `${item.name}, ${item.size_fmt}` : item.name}
        onClick={() => {
          if (selectionMode) {
            clearInspectTimer();
            onSelect?.(item.path);
            return;
          }
          if (isMobile) {
            if (isDir) onNavigate?.(item.path);
            else if (onInspect) onInspect(item);
            else onSelect?.(item);
            return;
          }
          clearInspectTimer();
          inspectTimer.current = setTimeout(() => {
            inspectTimer.current = null;
            if (onInspect) onInspect(item);
            else onSelect?.(item);
          }, SINGLE_CLICK_DELAY_MS);
        }}
        onDoubleClick={() => {
          clearInspectTimer();
          if (!selectionMode) onOpen?.();
        }}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            if (selectionMode) {
              clearInspectTimer();
              onSelect?.(item.path);
            }
            else {
              clearInspectTimer();
              onOpen?.();
            }
          }
        }}
      >
        {/* Thumbnail */}
        <div
          className="aspect-square flex items-center justify-center overflow-hidden rounded-t-lg relative"
          style={{ backgroundColor: 'var(--color-surface-hover)' }}
        >
          <LayeredPreview src={thumbnail} alt="" isDir={isDir} size="grid" />
        </div>
        {/* Info */}
        <div className="p-2.5">
          <p className="text-xs truncate font-medium" style={{ color: 'var(--color-text)' }}>{item.name}</p>
          {item.size_fmt && <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>{item.size_fmt}</p>}
        </div>
      </button>
      {!isDir && (
        <button
          type="button"
          aria-label={t('browse.select_zip', item.name)}
          aria-pressed={Boolean(selected)}
          className="absolute top-2 left-2 flex h-5 w-5 items-center justify-center rounded border-2 text-[10px] font-bold focus-visible:outline-none focus-visible:ring-2 transition-colors"
          style={{
            borderColor: selected ? 'var(--color-accent)' : 'var(--color-text-muted)',
            backgroundColor: selected ? 'var(--color-accent)' : 'rgba(0,0,0,0.5)',
            color: selected ? 'white' : 'transparent',
            '--tw-ring-color': 'var(--color-accent)',
          } as React.CSSProperties}
          onClick={e => {
            e.stopPropagation();
            zipSelect?.();
          }}
        >
        <span aria-hidden="true">✓</span>
        </button>
      )}
      {/* Copy link button */}
      {onCopyLink && (
        <button
          type="button"
          aria-label={t('browse.copy_link', item.name)}
          className={`absolute top-1.5 right-8 rounded p-1 opacity-0 transition-opacity hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100`}
          style={{ color: 'var(--color-text-secondary)' }}
          title={t('browse.copy_share_link')}
          onClick={e => { e.stopPropagation(); onCopyLink(item.path); }}
        >
          <Link2 size={14} aria-hidden="true" />
        </button>
      )}
      <button
        type="button"
        className="absolute top-1.5 right-1.5 rounded p-1.5 opacity-0 transition-opacity hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 group-hover:opacity-100"
        style={{ color: 'var(--color-text)', '--tw-ring-color': 'var(--color-accent)' } as React.CSSProperties}
        aria-label={t('browse.actions_for', item.name)}
        onClick={e => {
          e.stopPropagation();
          onContextMenu?.(e);
        }}
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {item.tags && item.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 px-2.5 pb-2.5">
          {item.tags.slice(0, 3).map(tag => (
            <button
              type="button"
              key={tag}
              onClick={e => { e.stopPropagation(); onTagClick?.(tag); }}
              className="rounded-full px-1.5 py-0.5 text-[10px] transition-colors focus-visible:outline-none focus-visible:ring-2"
              style={{
                backgroundColor: 'var(--color-accent-subtle)',
                color: 'var(--color-accent)',
                border: '1px solid var(--color-accent-border)',
                '--tw-ring-color': 'var(--color-accent)',
              } as React.CSSProperties}
            >
              {tag}
            </button>
          ))}
          {item.tags.length > 3 && (
            <span className="rounded-full px-1.5 py-0.5 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
              +{item.tags.length - 3}
            </span>
          )}
        </div>
      )}
      {(onInspect || onOpen || onDownload) && (
        <div className="flex items-center gap-1 border-t px-2.5 py-2" style={{ borderColor: 'var(--color-border)' }}>
          {onInspect && (
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 text-[10px] transition-colors hover:bg-slate-500/10 focus-visible:outline-none focus-visible:ring-2"
              style={{ color: 'var(--color-text-secondary)', '--tw-ring-color': 'var(--color-accent)' } as React.CSSProperties}
              aria-label={t('action.inspect', item.name)}
              onClick={event => { event.stopPropagation(); onInspect(item); }}
            >
              <Eye size={12} aria-hidden="true" />
              <span className="truncate">{t('action.inspect_short')}</span>
            </button>
          )}
          {onOpen && (
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 text-[10px] transition-colors hover:bg-indigo-500/10 focus-visible:outline-none focus-visible:ring-2"
              style={{ color: 'var(--color-accent-hover)', '--tw-ring-color': 'var(--color-accent)' } as React.CSSProperties}
              aria-label={isDir ? t('action.open_folder', item.name) : t('action.open_item', item.name)}
              onClick={event => { event.stopPropagation(); onOpen(); }}
            >
              <FolderOpen size={12} aria-hidden="true" />
              <span className="truncate">{t('action.open')}</span>
            </button>
          )}
          {onDownload && (
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 text-[10px] transition-colors hover:bg-emerald-500/10 focus-visible:outline-none focus-visible:ring-2"
              style={{ color: 'var(--color-success)', '--tw-ring-color': 'var(--color-accent)' } as React.CSSProperties}
              aria-label={isDir ? t('action.download_folder', item.name) : t('action.download_file', item.name)}
              onClick={event => { event.stopPropagation(); onDownload(); }}
            >
              <Download size={12} aria-hidden="true" />
              <span className="truncate">{t('action.download')}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
