import { Download, FileText, Link as LinkIcon, Share2, Tag, X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { BrowsableItem, Metadata } from '../../types/api';

interface InfoPanelProps {
  metadata: Metadata | null;
  selected?: BrowsableItem | null;
  loading?: boolean;
  onTagFilter?: (tag: string) => void;
  onDownload?: (item: BrowsableItem) => void;
  onShare?: (item: BrowsableItem) => void;
  onClose?: () => void;
}

export function InfoPanel({ metadata, selected, loading, onTagFilter, onDownload, onShare, onClose }: InfoPanelProps) {
  const { t } = useI18n();
  const externalUrls = metadata?.urls?.filter(url => {
    try {
      const protocol = new URL(url).protocol;
      return protocol === 'http:' || protocol === 'https:';
    } catch {
      return false;
    }
  }) ?? [];
  const previewUrl = selected?.thumbnail_url && (selected.category === 'image' || /\.(jpe?g|png|gif|webp|avif)$/i.test(selected.extension))
    ? selected.thumbnail_url
    : null;

  return (
    <section className="flex h-full flex-col" aria-label={t('info.title')}>
      <header className="flex items-center justify-between gap-2 border-b border-slate-700/50 px-4 py-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-200">{selected?.name ?? t('info.title')}</h3>
          {selected && <p className="text-xs text-slate-500">{selected.type === 'dir' ? 'Folder' : selected.extension || selected.category}</p>}
        </div>
        <div className="flex items-center gap-1">
          {onClose && <button type="button" onClick={onClose} aria-label={t('action.close_info')} className="p-1 text-slate-500 hover:text-white"><X size={15} aria-hidden="true" /></button>}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="space-y-3" aria-label="Loading inspection details">
            <div className="skeleton aspect-video w-full" />
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-4 w-1/2" />
            <div className="skeleton h-4 w-2/3" />
          </div>
        ) : !selected && !metadata ? (
          <p className="mt-8 text-center text-xs text-slate-500">{t('info.no_selection')}</p>
        ) : (
          <div className="space-y-5">
            {previewUrl && selected && <img src={previewUrl} alt={`${selected.name} preview`} className="aspect-video w-full rounded object-cover" />}
            {metadata?.tags?.length ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><Tag size={14} /> {t('info.tags')}</div><div className="flex flex-wrap gap-1.5">{metadata.tags.map(tag => <button key={tag} type="button" onClick={() => onTagFilter?.(tag)} className="rounded-full border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300 hover:bg-indigo-500/20">{tag}</button>)}</div></div> : null}
            {metadata?.notes ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><FileText size={14} /> {t('info.notes')}</div><p className="whitespace-pre-wrap text-sm text-slate-300">{metadata.notes}</p></div> : null}
            {externalUrls.length ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><LinkIcon size={14} /> {t('info.urls')}</div><div className="space-y-1">{externalUrls.map(url => <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="block truncate text-sm text-brand-400 hover:text-brand-300">{url}</a>)}</div></div> : null}
            {selected && <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-slate-700/50 pt-4 text-xs"><div><dt className="text-slate-500">Type</dt><dd className="mt-0.5 break-all text-slate-300">{selected.type === 'dir' ? 'Folder' : selected.extension || selected.category}</dd></div>{selected.size_fmt !== undefined && <div><dt className="text-slate-500">Size</dt><dd className="mt-0.5 text-slate-300">{selected.size_fmt}</dd></div>}{selected.modified !== undefined && <div><dt className="text-slate-500">Modified</dt><dd className="mt-0.5 text-slate-300">{new Date(selected.modified * 1000).toLocaleString()}</dd></div>}<div className="col-span-2"><dt className="text-slate-500">Path</dt><dd className="mt-0.5 break-all text-slate-300">{selected.path}</dd></div></dl>}
            {selected && (onDownload || onShare) && <div className="flex items-center gap-2 border-t border-slate-700/50 pt-4"><span className="text-xs text-slate-500">Actions</span>{onDownload && <button type="button" aria-label={t('action.download')} onClick={() => onDownload(selected)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><Download size={15} aria-hidden="true" /></button>}{onShare && <button type="button" aria-label={t('action.share')} onClick={() => onShare(selected)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><Share2 size={15} aria-hidden="true" /></button>}</div>}
          </div>
        )}
      </div>
    </section>
  );
}
