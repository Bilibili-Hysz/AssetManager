import { useEffect, useRef } from 'react';
import type { ProjectItem } from '../../types/api';
import { ProjectCard } from './ProjectCard';

interface ProjectGridProps {
  items: ProjectItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onCardClick?: (item: ProjectItem) => void;
  selectionMode?: boolean;
  onDoubleClick?: (item: ProjectItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: ProjectItem) => void;
  thumbnailMap: Record<string, string>;
  onDirectoryVisible?: (path: string) => void;
}

export function ProjectGrid({ items, selected, onSelect, onCardClick, selectionMode = false, onDoubleClick, onContextMenu, thumbnailMap, onDirectoryVisible }: ProjectGridProps) {
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
            onSelect(item.path);
            if (!selectionMode) onCardClick?.(item);
          }}
          onOpen={() => onDoubleClick?.(item)}
          onContextMenu={e => onContextMenu?.(e, item)}
          thumbnail={thumbnailMap[item.path]}
          />
        </div>
      ))}
    </div>
  );
}
