import { Columns3, Grid3x3, List, ArrowUpDown, CheckSquare, Download, X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { SortConfig } from '../../hooks/useProjects';

interface FileToolbarProps {
  sort: SortConfig;
  onSortChange: (config: SortConfig) => void;
  viewMode: 'grid' | 'list' | 'masonry';
  onViewModeChange: (mode: 'grid' | 'list' | 'masonry') => void;
  selectedCount: number;
  onDownloadSelected: () => void;
  isDownloadInFlight?: boolean;
  activeTag?: string | null;
  onClearTag?: () => void;
  selectMode?: boolean;
  onSelectModeToggle?: () => void;
}

export function FileToolbar({
  sort, onSortChange, viewMode, onViewModeChange,
  selectedCount, onDownloadSelected, isDownloadInFlight = false, activeTag, onClearTag, selectMode = false, onSelectModeToggle,
}: FileToolbarProps) {
  const { t } = useI18n();

  return (
    <div
      data-testid="file-toolbar"
      className="flex items-center gap-3 px-4 py-1.5 flex-shrink-0 transition-theme"
      style={{
        borderBottom: '1px solid var(--color-border)',
        backgroundColor: 'var(--color-surface)',
      }}
    >
      {/* Sort */}
      <div className="flex items-center gap-1.5">
        <ArrowUpDown size={13} style={{ color: 'var(--color-text-muted)' }} />
        <select
          value={sort.sort}
          onChange={e => onSortChange({ ...sort, sort: e.target.value })}
          aria-label={t('sort.by')}
          className="rounded-md px-2 py-1 text-[11px] transition-colors"
          style={{
            backgroundColor: 'var(--input-bg)',
            border: '1px solid var(--input-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="name">{t('sort.name')}</option>
          <option value="date">{t('sort.date')}</option>
          <option value="size">{t('sort.size')}</option>
        </select>
        <button
          type="button"
          onClick={() => onSortChange({ ...sort, order: sort.order === 'asc' ? 'desc' : 'asc' })}
          aria-label={sort.order === 'asc' ? t('sort.desc') : t('sort.asc')}
          className="px-1.5 py-1 text-[11px] rounded-md transition-colors"
          style={{
            backgroundColor: 'var(--input-bg)',
            border: '1px solid var(--input-border)',
            color: 'var(--color-text-secondary)',
          }}
        >
          {sort.order === 'asc' ? '↑' : '↓'}
        </button>
      </div>

      <div className="flex-1" />

      {activeTag && (
        <div
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px]"
          style={{
            backgroundColor: 'var(--color-accent-subtle)',
            border: '1px solid var(--color-accent-border)',
            color: 'var(--color-accent)',
          }}
        >
          <span>{activeTag}</span>
          <button type="button" onClick={onClearTag} aria-label={t('browse.clear_tag_named', activeTag)} style={{ color: 'var(--color-accent)' }}>
            <X size={13} aria-hidden="true" />
          </button>
        </div>
      )}

      {onSelectModeToggle && (
        <button
          type="button"
          onClick={onSelectModeToggle}
          aria-pressed={selectMode}
          className="hidden items-center gap-1 rounded-md px-2.5 py-1 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 md:flex"
          style={{
            backgroundColor: selectMode ? 'var(--color-accent-subtle)' : 'var(--input-bg)',
            border: `1px solid ${selectMode ? 'var(--color-accent-border)' : 'var(--input-border)'}`,
            color: selectMode ? 'var(--color-accent-hover)' : 'var(--color-text-secondary)',
            '--tw-ring-color': 'var(--color-accent)',
          } as React.CSSProperties}
        >
          <CheckSquare size={13} aria-hidden="true" />
          {selectMode ? t('browse.done') : t('browse.select')}
        </button>
      )}

      {/* Selected count + download */}
      <button
        type="button"
        onClick={onDownloadSelected}
        disabled={selectedCount === 0 || isDownloadInFlight}
        aria-label={t('browse.download_selected_zip', selectedCount)}
        className="flex items-center gap-1 px-2.5 py-1 text-[11px] text-white rounded-md transition-colors disabled:cursor-not-allowed"
        style={{
          backgroundColor: selectedCount > 0 && !isDownloadInFlight ? 'var(--color-accent)' : 'var(--color-elevated)',
          opacity: selectedCount > 0 && !isDownloadInFlight ? 1 : 0.6,
        }}
      >
        <Download size={13} aria-hidden="true" />
        {isDownloadInFlight ? t('browse.downloading_zip') : t('browse.selected').replace('{0}', String(selectedCount))}
      </button>

      {/* View mode */}
      <div
        className="flex items-center rounded-md overflow-hidden"
        style={{ border: '1px solid var(--color-border)' }}
      >
        <button
          type="button"
          onClick={() => onViewModeChange('masonry')}
          aria-label={t('view.masonry')}
          aria-pressed={viewMode === 'masonry'}
          className="p-1.5 transition-colors"
          style={{
            backgroundColor: viewMode === 'masonry' ? 'var(--color-elevated)' : 'transparent',
            color: viewMode === 'masonry' ? 'var(--color-text)' : 'var(--color-text-muted)',
          }}
        >
          <Columns3 size={15} />
        </button>
        <button
          type="button"
          onClick={() => onViewModeChange('grid')}
          aria-label={t('view.grid')}
          aria-pressed={viewMode === 'grid'}
          className="p-1.5 transition-colors"
          style={{
            backgroundColor: viewMode === 'grid' ? 'var(--color-elevated)' : 'transparent',
            color: viewMode === 'grid' ? 'var(--color-text)' : 'var(--color-text-muted)',
          }}
        >
          <Grid3x3 size={15} />
        </button>
        <button
          type="button"
          onClick={() => onViewModeChange('list')}
          aria-label={t('view.list')}
          aria-pressed={viewMode === 'list'}
          className="p-1.5 transition-colors"
          style={{
            backgroundColor: viewMode === 'list' ? 'var(--color-elevated)' : 'transparent',
            color: viewMode === 'list' ? 'var(--color-text)' : 'var(--color-text-muted)',
          }}
        >
          <List size={15} />
        </button>
      </div>
    </div>
  );
}
