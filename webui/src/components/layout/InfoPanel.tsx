import { Tag, FileText, Link as LinkIcon, X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { Metadata } from '../../types/api';

interface InfoPanelProps {
  metadata: Metadata | null;
  loading?: boolean;
  onTagClick?: (tag: string) => void;
  onClose?: () => void;
}

export function InfoPanel({ metadata, loading, onTagClick, onClose }: InfoPanelProps) {
  const { t } = useI18n();

  return (
    <div className="flex flex-col h-full">
      {/* Header with close button */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700/50 flex-shrink-0">
        <h3 className="text-xs font-semibold text-slate-300">{t('info.title')}</h3>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 text-slate-500 hover:text-white hover:bg-slate-800/50 rounded transition-colors"
          >
            <X size={14} />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="space-y-3">
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-4 w-1/2" />
            <div className="skeleton h-4 w-2/3" />
          </div>
        ) : !metadata ? (
          <p className="text-xs text-slate-500 text-center mt-8">{t('info.no_selection')}</p>
        ) : (
          <div className="space-y-5">
            {/* Tags */}
            {metadata.tags && metadata.tags.length > 0 && (
              <div>
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                  <Tag size={14} /> {t('info.tags')}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {metadata.tags.map(tag => (
                    <button
                      key={tag}
                      onClick={() => onTagClick?.(tag)}
                      className="px-2 py-0.5 rounded-full text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 hover:bg-indigo-500/20 transition-colors"
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* Notes */}
            {metadata.notes && (
              <div>
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                  <FileText size={14} /> {t('info.notes')}
                </div>
                <p className="text-sm text-slate-300 whitespace-pre-wrap">{metadata.notes}</p>
              </div>
            )}
            {/* URLs */}
            {metadata.urls && metadata.urls.length > 0 && (
              <div>
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                  <LinkIcon size={14} /> {t('info.urls')}
                </div>
                <div className="space-y-1">
                  {metadata.urls.map((url, i) => (
                    <a key={i} href={url} target="_blank" rel="noopener noreferrer"
                      className="block text-sm text-brand-400 hover:text-brand-300 truncate transition-colors">
                      {url}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}