import { useEffect, useRef } from 'react';
import type { BrowsableItem } from '../../types/api';
import { ProjectCard } from './ProjectCard';

interface ProjectGridProps {
  items: BrowsableItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onZipSelect?: (path: string) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  selectionMode?: boolean;
  onDoubleClick?: (item: BrowsableItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: BrowsableItem) => void;
  thumbnailMap: Record<string, string>;
  onDirectoryVisible?: (path: string) => void;
}

export function ProjectGrid({ items, selected, onSelect, onZipSelect = onSelect, onInspect, onNavigate, selectionMode = false, onDoubleClick, onContextMenu, thumbnailMap, onDirectoryVisible }: ProjectGridProps) {
  const nodes = useRef(new Map<string, HTMLDivElement>());

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
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 p-4">
      {items.map(item => (
        <div key={item.path} data-directory-path={item.type === 'dir' ? item.path : undefined}
          ref={node => {
            if (node && item.type === 'dir') nodes.current.set(item.path, node);
            else nodes.current.delete(item.path);
          }}>
          <ProjectCard
            item={item}
            selected={selected.has(item.path)}
            onSelect={() => {
              if (item.type === 'dir') onNavigate?.(item.path);
              else if (selectionMode) onSelect(item.path);
              else onInspect?.(item);
            }}
            onZipSelect={() => onZipSelect(item.path)}
           onOpen={() => {
             if (item.type === 'dir') onNavigate?.(item.path);
             else onDoubleClick?.(item);
           }}
          onContextMenu={e => onContextMenu?.(e, item)}
          thumbnail={thumbnailMap[item.path]}
          />
        </div>
      ))}
    </div>
  );
}
