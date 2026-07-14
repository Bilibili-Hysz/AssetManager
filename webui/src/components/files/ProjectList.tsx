import { Folder, File } from 'lucide-react';
import type { ProjectItem } from '../../types/api';

interface ProjectListProps {
  items: ProjectItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onDoubleClick?: (item: ProjectItem) => void;
  onContextMenu?: (e: React.MouseEvent, item: ProjectItem) => void;
}

export function ProjectList({ items, selected, onSelect, onDoubleClick, onContextMenu }: ProjectListProps) {
  return (
    <div className="p-4">
      <div className="border border-slate-700/50 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50 bg-slate-800/50">
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2 w-8" />
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2">Name</th>
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2 w-20">Size</th>
              <th className="text-left text-[11px] text-slate-500 font-medium px-3 py-2 w-32 hidden md:table-cell">Modified</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => {
              const isDir = item.type === 'dir';
              return (
                <tr
                  key={item.path}
                  className={`border-b border-slate-800/50 transition-colors cursor-pointer
                    ${selected.has(item.path) ? 'bg-indigo-500/5' : 'hover:bg-slate-800/30'}`}
                  onClick={() => onSelect(item.path)}
                  onDoubleClick={() => onDoubleClick?.(item)}
                  onContextMenu={e => onContextMenu?.(e, item)}
                >
                  <td className="px-3 py-2.5">
                    {isDir ? <Folder size={16} className="text-amber-400" /> : <File size={16} className="text-slate-500" />}
                  </td>
                  <td className="px-3 py-2.5 text-sm text-slate-200">{item.name}</td>
                  <td className="px-3 py-2.5 text-sm text-slate-400">{item.size_fmt}</td>
                  <td className="px-3 py-2.5 text-sm text-slate-500 hidden md:table-cell">
                    {new Date(item.modified * 1000).toLocaleDateString()}
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