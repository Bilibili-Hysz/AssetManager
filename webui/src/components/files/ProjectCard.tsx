import { useState } from 'react';
import { Folder, File, MoreHorizontal } from 'lucide-react';
import type { BrowsableItem } from '../../types/api';

interface ProjectCardProps {
  item: BrowsableItem;
  selected?: boolean;
  onSelect?: () => void;
  onZipSelect?: () => void;
  onOpen?: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  thumbnail?: string;
}

export function ProjectCard({ item, selected, onSelect, onZipSelect = onSelect, onOpen, onContextMenu, thumbnail }: ProjectCardProps) {
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
      onContextMenu={onContextMenu}
    >
      <button
        type="button"
        className="block w-full text-left rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-400"
        aria-label={item.size_fmt ? `${item.name}, ${item.size_fmt}` : item.name}
        onClick={onSelect}
        onDoubleClick={onOpen}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            onOpen?.();
          }
        }}
      >
        {/* Thumbnail */}
        <div className="aspect-square flex items-center justify-center overflow-hidden rounded-t-lg bg-slate-800/50">
          {thumbnail ? (
            <img src={thumbnail} alt="" className="w-full h-full object-cover" />
          ) : isDir ? (
            <Folder size={36} className="text-amber-400/70" aria-hidden="true" />
          ) : (
            <File size={36} className="text-slate-500" aria-hidden="true" />
          )}
        </div>
        {/* Info */}
        <div className="p-2.5">
          <p className="text-xs text-slate-200 truncate font-medium">{item.name}</p>
          {item.size_fmt && <p className="text-[11px] text-slate-500 mt-0.5">{item.size_fmt}</p>}
        </div>
      </button>
      {!isDir && (
        <button
          type="button"
          aria-label={`Select ${item.name} for ZIP download`}
          aria-pressed={Boolean(selected)}
          className={`absolute top-2 left-2 flex h-5 w-5 items-center justify-center rounded border-2 text-[10px] font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${selected ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-slate-500 bg-slate-900/80 text-transparent hover:border-indigo-400'}`}
          onClick={e => {
            e.stopPropagation();
            onZipSelect?.();
          }}
        >
          <span aria-hidden="true">✓</span>
        </button>
      )}
      <button
        type="button"
        className="absolute top-1.5 right-1.5 rounded p-1.5 text-slate-300 opacity-0 transition-opacity hover:bg-slate-700/80 hover:text-white focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 group-hover:opacity-100"
        aria-label={`Actions for ${item.name}`}
        onClick={e => {
          e.stopPropagation();
          onContextMenu?.(e);
        }}
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
