import { useEffect, useRef } from 'react';
import type { BrowsableItem } from '../../types/api';
import { ProjectCard } from './ProjectCard';

interface ProjectGridProps {
  items: BrowsableItem[];
  selected: Set<string>;
  onSelect: ((value: string | BrowsableItem) => void) | ((path: string) => void);
  onZipSelect?: (path: string) => void;
  onInspect?: (item: BrowsableItem) => void;
  onNavigate?: (path: string) => void;
  selectionMode?: boolean;
  onDoubleClick?: (item: BrowsableItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: BrowsableItem) => void;
  thumbnailMap: Record<string, string>;
  onDirectoryVisible?: (path: string) => void;
  onTagClick?: (tag: string) => void;
  onCopyLink?: (path: string) => void;
  isMobile?: boolean;
}

export function ProjectGrid({ items, selected, onSelect, onZipSelect = onSelect, onInspect, onNavigate, selectionMode = false, onDoubleClick, onContextMenu, thumbnailMap, onDirectoryVisible, onTagClick, onCopyLink, isMobile = false }: ProjectGridProps) {
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
    <div data-testid="project-grid" className="grid w-full min-w-0 grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3 p-4">
      {items.map(item => (
        <div key={item.path} data-directory-path={item.type === 'dir' ? item.path : undefined}
          ref={node => {
            if (node && item.type === 'dir') nodes.current.set(item.path, node);
            else nodes.current.delete(item.path);
          }}>
          <ProjectCard
            item={item}
            selected={selected.has(item.path)}
            selectionMode={selectionMode}
            isMobile={isMobile}
            onNavigate={onNavigate}
            onSelect={selectedItem => {
              const selectedPath = typeof selectedItem === 'string' ? selectedItem : selectedItem.path;
              const selectedItemValue = typeof selectedItem === 'string' ? item : selectedItem;
              if (selectionMode) (onSelect as (path: string) => void)(selectedPath);
              else if (isMobile && selectedItemValue.type === 'dir') onNavigate?.(selectedPath);
              else onInspect?.(selectedItemValue);
            }}
            onZipSelect={() => onZipSelect(item.path)}
           onOpen={() => onDoubleClick?.(item)}
          onContextMenu={e => onContextMenu?.(e, item)}
          thumbnail={thumbnailMap[item.path]}
           onTagClick={onTagClick}
           onCopyLink={onCopyLink}
           />
        </div>
      ))}
    </div>
  );
}
