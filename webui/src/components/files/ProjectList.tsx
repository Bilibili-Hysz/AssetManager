import { useEffect, useRef } from 'react';
import { Folder, File, MoreHorizontal } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { BrowsableItem } from '../../types/api';

interface ProjectListProps {
  items: BrowsableItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onZipSelect?: (path: string) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  selectionMode?: boolean;
  onDoubleClick?: (item: BrowsableItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: BrowsableItem) => void;
  onDirectoryVisible?: (path: string) => void;
}

export function ProjectList({ items, selected, onSelect, onZipSelect = onSelect, onInspect, onNavigate, selectionMode = false, onDoubleClick, onContextMenu, onDirectoryVisible }: ProjectListProps) {
  const { t } = useI18n();
  const nodes = useRef(new Map<string, HTMLTableRowElement>());

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

  return (
    <div className="p-4">
      <div className="border border-slate-700/50 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50 bg-slate-800/50">
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2 w-8" />
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2">{t('sort.name')}</th>
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2 w-20">{t('sort.size')}</th>
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2 w-32 hidden md:table-cell">{t('info.modified')}</th>
              <th className="w-10"><span className="sr-only">{t('action.actions')}</span></th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => {
              const isDir = item.type === 'dir';
              return (
                <tr
                  key={item.path}
                  data-directory-path={isDir ? item.path : undefined}
                  ref={node => {
                    if (node && isDir) nodes.current.set(item.path, node);
                    else nodes.current.delete(item.path);
                  }}
                  className={`border-b border-slate-800/50 transition-colors cursor-pointer
                    ${selected.has(item.path) ? 'bg-indigo-500/5' : 'hover:bg-slate-800/30'}`}
                  onClick={() => {
                    if (isDir) onNavigate?.(item.path);
                    else if (selectionMode) onSelect(item.path);
                    else onInspect?.(item);
                  }}
                  onDoubleClick={() => {
                    if (isDir) onNavigate?.(item.path);
                    else onDoubleClick?.(item);
                  }}
                  onContextMenu={e => onContextMenu?.(e, item)}
                >
                  <td className="px-3 py-2.5">
                    {!isDir && (
                      <button
                        type="button"
                        aria-label={`Select ${item.name} for ZIP download`}
                        aria-pressed={selected.has(item.path)}
                        className={`mr-2 inline-flex h-5 w-5 items-center justify-center rounded border-2 text-[10px] font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${selected.has(item.path) ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-slate-500 text-transparent hover:border-indigo-400'}`}
                        onClick={e => {
                          e.stopPropagation();
                          onZipSelect(item.path);
                        }}
                      >
                        <span aria-hidden="true">✓</span>
                      </button>
                    )}
                    {isDir ? <Folder size={16} className="text-amber-400" aria-hidden="true" /> : <File size={16} className="text-slate-500" aria-hidden="true" />}
                  </td>
                  <td className="px-3 py-2.5 text-sm text-slate-200">
                    <button
                      type="button"
                      className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                      aria-pressed={selected.has(item.path)}
                      onClick={e => {
                        e.stopPropagation();
                        if (isDir) onNavigate?.(item.path);
                        else if (selectionMode) onSelect(item.path);
                        else onInspect?.(item);
                      }}
                      onDoubleClick={e => {
                        e.stopPropagation();
                        if (isDir) onNavigate?.(item.path);
                        else onDoubleClick?.(item);
                      }}
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          if (isDir) onNavigate?.(item.path);
                          else onDoubleClick?.(item);
                        }
                      }}
                    >
                      {item.name}
                    </button>
                  </td>
                  <td className="px-3 py-2.5 text-sm text-slate-400">{item.size_fmt}</td>
                  <td className="px-3 py-2.5 text-sm text-slate-500 hidden md:table-cell">
                    {item.modified !== undefined && new Date(item.modified * 1000).toLocaleDateString()}
                  </td>
                  <td className="px-2 py-2.5">
                    <button
                      type="button"
                      className="rounded p-1 text-slate-400 hover:bg-slate-700/50 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                      aria-label={t('action.item_actions', item.name)}
                      onClick={e => {
                        e.stopPropagation();
                        onContextMenu?.(e, item);
                      }}
                    >
                      <MoreHorizontal size={16} aria-hidden="true" />
                    </button>
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
