import type { ProjectItem } from '../../types/api';
import { ProjectCard } from './ProjectCard';

interface ProjectGridProps {
  items: ProjectItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onCardClick?: (item: ProjectItem) => void;
  onDoubleClick?: (item: ProjectItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: ProjectItem) => void;
  thumbnailMap: Record<string, string>;
}

export function ProjectGrid({ items, selected, onSelect, onCardClick, onDoubleClick, onContextMenu, thumbnailMap }: ProjectGridProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 p-4">
      {items.map(item => (
        <ProjectCard
          key={item.path}
          item={item}
          selected={selected.has(item.path)}
          onSelect={() => {
            onSelect(item.path);
            onCardClick?.(item);
          }}
          onOpen={() => onDoubleClick?.(item)}
          onContextMenu={e => onContextMenu?.(e, item)}
          thumbnail={thumbnailMap[item.path]}
        />
      ))}
    </div>
  );
}
