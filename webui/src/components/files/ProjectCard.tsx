import { useState } from 'react';
import { Folder, File } from 'lucide-react';
import type { ProjectItem } from '../../types/api';

interface ProjectCardProps {
  item: ProjectItem;
  selected?: boolean;
  onSelect?: () => void;
  onDoubleClick?: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  thumbnail?: string;
}

export function ProjectCard({ item, selected, onSelect, onDoubleClick, onContextMenu, thumbnail }: ProjectCardProps) {
  const [hover, setHover] = useState(false);
  const isDir = item.type === 'dir';

  return (
    <div
      className={`relative rounded-lg border transition-all duration-200 cursor-pointer group
        ${selected
          ? 'border-indigo-500/50 bg-indigo-500/5'
          : hover
            ? 'border-slate-600/50 bg-slate-800/40'
            : 'border-slate-700/50 bg-slate-900/50'
        }`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onSelect}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
    >
      {/* Thumbnail */}
      <div className="aspect-square flex items-center justify-center overflow-hidden rounded-t-lg bg-slate-800/50">
        {thumbnail ? (
          <img src={thumbnail} alt={item.name} className="w-full h-full object-cover" />
        ) : isDir ? (
          <Folder size={36} className="text-amber-400/70" />
        ) : (
          <File size={36} className="text-slate-500" />
        )}
      </div>
      {/* Info */}
      <div className="p-2.5">
        <p className="text-xs text-slate-200 truncate font-medium">{item.name}</p>
        <p className="text-[11px] text-slate-500 mt-0.5">{item.size_fmt}</p>
      </div>
      {/* Selection checkbox */}
      <div className={`absolute top-2 left-2 transition-opacity ${hover || selected ? 'opacity-100' : 'opacity-0'}`}>
        <div className={`w-4 h-4 rounded border-2 flex items-center justify-center
          ${selected ? 'bg-indigo-500 border-indigo-500' : 'bg-slate-900/80 border-slate-500'}`}>
          {selected && <span className="text-white text-[10px] font-bold">✓</span>}
        </div>
      </div>
    </div>
  );
}