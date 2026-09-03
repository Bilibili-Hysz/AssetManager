import { useEffect, useRef } from 'react';
import { Download, Eye, FolderOpen, MoreHorizontal, Link2 } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { BrowsableItem } from '../../types/api';
import { LayeredPreview } from './LayeredPreview';
import { SINGLE_CLICK_DELAY_MS } from './ProjectCard';

interface ProjectListProps {
  items: BrowsableItem[];
  selected: Set<string>;
  onSelect: ((value: string | BrowsableItem) => void) | ((path: string) => void);
  onZipSelect?: (path: string) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  selectionMode?: boolean;
  onDoubleClick?: (item: BrowsableItem) => void;
  onDownload?: (item: BrowsableItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: BrowsableItem) => void;
  onDirectoryVisible?: (path: string) => void;
  onTagClick?: (tag: string) => void;
  onCopyLink?: (path: string) => void;
  thumbnailMap?: Record<string, string>;
  isMobile?: boolean;
}

export function ProjectList({ items, selected, onSelect, onZipSelect = onSelect, onInspect, onNavigate, selectionMode = false, onDoubleClick, onDownload, onContextMenu, onDirectoryVisible, onTagClick, onCopyLink, thumbnailMap = {}, isMobile = false }: ProjectListProps) {
  const { t } = useI18n();
  const nodes = useRef(new Map<string, HTMLTableRowElement>());
  const inspectTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const clearInspectTimer = (path: string) => {
    const timer = inspectTimers.current.get(path);
    if (timer !== undefined) {
      clearTimeout(timer);
      inspectTimers.current.delete(path);
    }
  };

  const scheduleInspect = (item: BrowsableItem) => {
    clearInspectTimer(item.path);
    inspectTimers.current.set(item.path, setTimeout(() => {
      inspectTimers.current.delete(item.path);
      onInspect?.(item);
    }, SINGLE_CLICK_DELAY_MS));
  };

  const handleSingleClick = (item: BrowsableItem) => {
    clearInspectTimer(item.path);
    if (selectionMode) (onSelect as (path: string) => void)(item.path);
    else if (isMobile) {
      if (item.type === 'dir') onNavigate?.(item.path);
      else onInspect?.(item);
    } else scheduleInspect(item);
  };

  useEffect(() => {
    if (!onDirectoryVisible || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) onDirectoryVisible(entry.target.getAttribute('data-directory-path') ?? '');
      }
    }, { rootMargin: '160px' });
    for (const node of nodes.current.values()) observer.observe(node);
    return () => observer.disconnect();
  }, [items, onDirectoryVisible]);

  useEffect(() => () => {
    for (const timer of inspectTimers.current.values()) clearTimeout(timer);
    inspectTimers.current.clear();
  }, []);

  return (
    <div className="p-4">
      <div className="border border-[var(--color-border)] rounded-xl overflow-hidden bg-[var(--color-surface)] shadow-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-[var(--color-surface-hover)]/40">
              <th scope="col" className="text-left text-[11px] text-[var(--color-text-muted)] font-medium px-3 py-2.5 w-8" />
              <th scope="col" className="text-left text-[11px] text-[var(--color-text-muted)] font-medium px-3 py-2.5">{t('sort.name')}</th>
              <th scope="col" className="text-left text-[11px] text-[var(--color-text-muted)] font-medium px-3 py-2.5 w-20">{t('sort.size')}</th>
              <th scope="col" className="text-left text-[11px] text-[var(--color-text-muted)] font-medium px-3 py-2.5 w-32 hidden md:table-cell">{t('info.modified')}</th>
              <th scope="col" className="w-10"><span className="sr-only">{t('action.actions')}</span></th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => {
              const isDir = item.type === 'dir';
              const isSelected = selected.has(item.path);
              return (
                <tr
                  key={item.path}
                  data-directory-path={isDir ? item.path : undefined}
                  ref={node => {
                    if (node && isDir) nodes.current.set(item.path, node);
                    else nodes.current.delete(item.path);
                  }}
                  className={`border-b border-[var(--color-border)]/60 transition-colors cursor-pointer ${
                    isSelected ? 'bg-[var(--color-accent-subtle)]' : 'hover:bg-[var(--color-surface-hover)]'
                  }`}
                  onClick={() => handleSingleClick(item)}
                  onDoubleClick={() => {
                    clearInspectTimer(item.path);
                    onDoubleClick?.(item);
                  }}
                  onContextMenu={e => onContextMenu?.(e, item)}
                >
                  <td className="px-3 py-2.5">
                    {!isDir && (
                      <button
                        type="button"
                        aria-label={t('browse.select_zip', item.name)}
                        aria-pressed={selected.has(item.path)}
                        className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded border-2 text-[10px] font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                        style={{
                          backgroundColor: isSelected ? 'var(--color-accent)' : 'transparent',
                          borderColor: isSelected ? 'var(--color-accent)' : 'var(--color-border-strong)',
                          color: isSelected ? 'var(--color-text-inverse)' : 'transparent',
                        }}
                        onClick={e => {
                          e.stopPropagation();
                          onZipSelect(item.path);
                        }}
                      >
                        <span aria-hidden="true">✓</span>
                      </button>
                    )}
                    <LayeredPreview src={thumbnailMap[item.path]} alt={item.name} isDir={isDir} size="list" />
                  </td>
                  <td className="px-3 py-2.5 text-sm text-[var(--color-text)]">
                    <button
                      type="button"
                      className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                      aria-pressed={selected.has(item.path)}
                      onClick={e => {
                        e.stopPropagation();
                        handleSingleClick(item);
                      }}
                      onDoubleClick={e => {
                        e.stopPropagation();
                        clearInspectTimer(item.path);
                        onDoubleClick?.(item);
                      }}
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          if (selectionMode) (onSelect as (path: string) => void)(item.path);
                          else {
                            clearInspectTimer(item.path);
                            onDoubleClick?.(item);
                          }
                        }
                      }}
                    >
                      <span className="block truncate">{item.name}</span>
                    </button>
                    {item.tags && item.tags.length > 0 && <span className="mt-1 flex flex-wrap gap-1">
                      {item.tags.slice(0, 3).map(tag => <button key={tag} type="button" onClick={event => { event.stopPropagation(); onTagClick?.(tag); }} className="rounded-full border border-[var(--color-accent)]/20 bg-[var(--color-accent-subtle)] px-2 py-0.5 text-[10px] text-[var(--color-accent)] hover:bg-[var(--color-accent-subtle)]/80 transition-colors">{tag}</button>)}
                      {item.tags.length > 3 && <span className="px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]">+{item.tags.length - 3}</span>}
                    </span>}
                  </td>
                  <td className="px-3 py-2.5 text-sm text-[var(--color-text-muted)]">{item.size_fmt}</td>
                  <td className="px-3 py-2.5 text-sm text-[var(--color-text-muted)] hidden md:table-cell">
                    {item.modified !== undefined && new Date(item.modified * 1000).toLocaleDateString()}
                  </td>
                   <td className="px-2 py-2.5">
                     <div className="flex items-center justify-end gap-1">
                     {onInspect && (
                       <button
                         type="button"
                         className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                         aria-label={t('action.inspect', item.name)}
                         title={t('action.inspect', item.name)}
                         onClick={e => { e.stopPropagation(); clearInspectTimer(item.path); onInspect(item); }}
                       >
                         <Eye size={14} aria-hidden="true" />
                         <span className="hidden lg:inline">{t('action.inspect_short')}</span>
                       </button>
                     )}
                     {onDoubleClick && (
                       <button
                         type="button"
                         className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent-subtle)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                         aria-label={isDir ? t('action.open_folder', item.name) : t('action.open_item', item.name)}
                         title={isDir ? t('action.open_folder', item.name) : t('action.open_item', item.name)}
                         onClick={e => { e.stopPropagation(); clearInspectTimer(item.path); onDoubleClick(item); }}
                       >
                         <FolderOpen size={14} aria-hidden="true" />
                         <span className="hidden lg:inline">{t('action.open')}</span>
                       </button>
                     )}
                     {onDownload && (
                       <button
                         type="button"
                         className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-emerald-400 transition-colors hover:bg-emerald-500/10 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                         aria-label={isDir ? t('action.download_folder', item.name) : t('action.download_file', item.name)}
                         title={isDir ? t('action.download_folder', item.name) : t('action.download_file', item.name)}
                         onClick={e => { e.stopPropagation(); clearInspectTimer(item.path); onDownload(item); }}
                       >
                         <Download size={14} aria-hidden="true" />
                         <span className="hidden lg:inline">{t('action.download')}</span>
                       </button>
                     )}
                     {onCopyLink && (
                       <button
                         type="button"
                         className="rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                         aria-label={t('browse.copy_link', item.name)}
                         title={t('browse.copy_share_link')}
                         onClick={e => { e.stopPropagation(); onCopyLink(item.path); }}
                       >
                         <Link2 size={15} aria-hidden="true" />
                       </button>
                     )}
                     <button
                      type="button"
                      className="rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                      aria-label={t('action.item_actions', item.name)}
                      onClick={e => {
                        e.stopPropagation();
                        onContextMenu?.(e, item);
                      }}
                    >
                      <MoreHorizontal size={16} aria-hidden="true" />
                     </button>
                     </div>
                   </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
