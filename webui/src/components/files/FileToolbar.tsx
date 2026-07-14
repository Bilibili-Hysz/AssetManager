import { Grid3x3, List, ArrowUpDown, Download } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { SortConfig } from '../../hooks/useProjects';

interface FileToolbarProps {
  sort: SortConfig;
  onSortChange: (config: SortConfig) => void;
  viewMode: 'grid' | 'list';
  onViewModeChange: (mode: 'grid' | 'list') => void;
  selectedCount: number;
  onDownloadSelected: () => void;
}

export function FileToolbar({
  sort, onSortChange, viewMode, onViewModeChange,
  selectedCount, onDownloadSelected,
}: FileToolbarProps) {
  const { t } = useI18n();

  return (
    <div className="flex items-center gap-3 px-4 py-1.5 border-b border-slate-700/50 bg-slate-900/30 flex-shrink-0">
      {/* Sort */}
      <div className="flex items-center gap-1.5">
        <ArrowUpDown size={13} className="text-slate-500" />
        <select
          value={sort.sort}
          onChange={e => onSortChange({ ...sort, sort: e.target.value })}
          className="bg-slate-800 border border-slate-700/50 rounded-md px-2 py-1 text-[11px] text-slate-300
            focus:outline-none focus:border-indigo-500/50 transition-colors"
        >
          <option value="name">{t('sort.name')}</option>
          <option value="date">{t('sort.date')}</option>
          <option value="size">{t('sort.size')}</option>
        </select>
        <button
          onClick={() => onSortChange({ ...sort, order: sort.order === 'asc' ? 'desc' : 'asc' })}
          className="px-1.5 py-1 text-[11px] text-slate-400 hover:text-white transition-colors bg-slate-800 border border-slate-700/50 rounded-md"
        >
          {sort.order === 'asc' ? '↑' : '↓'}
        </button>
      </div>

      <div className="flex-1" />

      {/* Selected count + download */}
      {selectedCount > 0 && (
        <button
          onClick={onDownloadSelected}
          className="flex items-center gap-1 px-2.5 py-1 text-[11px] text-white bg-indigo-500 hover:bg-indigo-600 rounded-md transition-colors"
        >
          <Download size={13} />
          {t('browse.selected').replace('{0}', String(selectedCount))}
        </button>
      )}

      {/* View mode */}
      <div className="flex items-center border border-slate-700/50 rounded-md overflow-hidden">
        <button
          onClick={() => onViewModeChange('grid')}
          className={`p-1.5 transition-colors ${viewMode === 'grid' ? 'bg-slate-700 text-slate-200' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <Grid3x3 size={15} />
        </button>
        <button
          onClick={() => onViewModeChange('list')}
          className={`p-1.5 transition-colors ${viewMode === 'list' ? 'bg-slate-700 text-slate-200' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <List size={15} />
        </button>
      </div>
    </div>
  );
}