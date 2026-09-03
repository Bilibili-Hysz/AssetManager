import { useEffect, useRef, useState } from 'react';
import type { BrowsableItem } from '../../types/api';
import { ProjectCard } from './ProjectCard';

const INITIAL_BATCH_SIZE = 80;
const BATCH_INCREMENT = 60;

interface ProjectGridProps {
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
  thumbnailMap: Record<string, string>;
  onDirectoryVisible?: (path: string) => void;
  onTagClick?: (tag: string) => void;
  onCopyLink?: (path: string) => void;
  isMobile?: boolean;
}

export function ProjectGrid({
  items,
  selected,
  onSelect,
  onZipSelect = onSelect,
  onInspect,
  onNavigate,
  selectionMode = false,
  onDoubleClick,
  onDownload,
  onContextMenu,
  thumbnailMap,
  onDirectoryVisible,
  onTagClick,
  onCopyLink,
  isMobile = false,
}: ProjectGridProps) {
  const nodes = useRef(new Map<string, HTMLDivElement>());
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const [renderedCount, setRenderedCount] = useState<number>(INITIAL_BATCH_SIZE);

  // Reset or adjust rendered count when items change
  useEffect(() => {
    setRenderedCount(prev => (items.length <= INITIAL_BATCH_SIZE ? items.length : Math.min(items.length, Math.max(INITIAL_BATCH_SIZE, prev))));
  }, [items]);

  // Progressive batch expansion on scroll
  useEffect(() => {
    if (renderedCount >= items.length) return;
    const sentinel = sentinelRef.current;
    if (!sentinel || typeof IntersectionObserver === 'undefined') {
      setRenderedCount(items.length);
      return;
    }
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) {
          setRenderedCount(prev => Math.min(prev + BATCH_INCREMENT, items.length));
        }
      },
      { rootMargin: '400px' },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [items.length, renderedCount]);

  useEffect(() => {
    if (!onDirectoryVisible || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) onDirectoryVisible(entry.target.getAttribute('data-directory-path') ?? '');
        }
      },
      { rootMargin: '160px' },
    );
    for (const node of nodes.current.values()) observer.observe(node);
    return () => observer.disconnect();
  }, [items, onDirectoryVisible, renderedCount]);

  const visibleItems = items.length <= INITIAL_BATCH_SIZE ? items : items.slice(0, renderedCount);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const cards = e.currentTarget.querySelectorAll<HTMLElement>('[data-spotlight-card]');
    cards.forEach(card => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--mouse-x', `${x}px`);
      card.style.setProperty('--mouse-y', `${y}px`);
    });
  };

  return (
    <div
      data-testid="project-grid"
      className="grid w-full min-w-0 gap-3 p-4 grid-cols-[repeat(auto-fill,minmax(168px,1fr))]"
      style={{ justifyContent: 'start' }}
      onMouseMove={handleMouseMove}
    >
      {visibleItems.map(item => (
        <div
          key={item.path}
          data-directory-path={item.type === 'dir' ? item.path : undefined}
          ref={node => {
            if (node && item.type === 'dir') nodes.current.set(item.path, node);
            else nodes.current.delete(item.path);
          }}
        >
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
            onDownload={onDownload ? () => onDownload(item) : undefined}
            onContextMenu={e => onContextMenu?.(e, item)}
            thumbnail={thumbnailMap[item.path]}
            onTagClick={onTagClick}
            onCopyLink={onCopyLink}
          />
        </div>
      ))}
      {renderedCount < items.length && (
        <div
          ref={sentinelRef}
          data-testid="project-grid-sentinel"
          className="col-span-full h-8 flex items-center justify-center text-xs opacity-60"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
