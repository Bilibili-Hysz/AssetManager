import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal, Lock, Download, Link2 } from 'lucide-react';
import type { BrowsableItem } from '../../types/api';
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
  onContextMenu,
  thumbnail,
  onTagClick,
  onCopyLink,
}: ProjectCardProps) {
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

  // Permission badges
  const badges = [];
  if (item.view_only) badges.push({ icon: <Lock size={10} />, title: 'View Only', color: 'bg-amber-500/20 text-amber-400' });
  if (item.downloadable === true) badges.push({ icon: <Download size={10} />, title: 'Downloadable', color: 'bg-emerald-500/20 text-emerald-400' });
  if (item.password_protected) badges.push({ icon: <Lock size={10} />, title: 'Password Protected', color: 'bg-red-500/20 text-red-400' });

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
          onOpen?.();
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
        <div className="aspect-square flex items-center justify-center overflow-hidden rounded-t-lg bg-slate-800/50 relative">
          <LayeredPreview src={thumbnail} alt="" isDir={isDir} size="grid" />
          {/* Permission badges overlay */}
          {badges.length > 0 && (
            <div className="absolute top-2 right-2 flex flex-col gap-1">
              {badges.map((badge, i) => (
                <span key={i} className={`p-1 rounded-md ${badge.color}`} title={badge.title}>
                  {badge.icon}
                </span>
              ))}
            </div>
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
            zipSelect?.();
          }}
        >
        <span aria-hidden="true">✓</span>
        </button>
      )}
      {item.tags && item.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 px-2.5 pb-2.5">
          {item.tags.slice(0, 3).map(tag => (
            <button
              key={tag}
              type="button"
              onClick={() => onTagClick?.(tag)}
              className="rounded-full border border-indigo-500/20 bg-indigo-500/10 px-1.5 py-0.5 text-[10px] text-indigo-300 transition-colors hover:bg-indigo-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              {tag}
            </button>
          ))}
          {item.tags.length > 3 && <span className="rounded-full px-1.5 py-0.5 text-[10px] text-slate-500">+{item.tags.length - 3}</span>}
        </div>
      )}
      {/* Copy link button */}
      {onCopyLink && (
        <button
          type="button"
          aria-label={`Copy link for ${item.name}`}
          className={`absolute top-1.5 right-8 rounded p-1 text-slate-400 opacity-0 transition-opacity hover:bg-slate-700/80 hover:text-white focus-visible:opacity-100 group-hover:opacity-100 ${hover ? 'opacity-100' : ''}`}
          title="Copy share link"
          onClick={e => { e.stopPropagation(); onCopyLink(item.path); }}
        >
          <Link2 size={14} aria-hidden="true" />
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
