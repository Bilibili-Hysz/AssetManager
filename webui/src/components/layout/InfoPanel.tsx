import { useEffect, useRef, useState } from 'react';
import { Download, FileText, Link as LinkIcon, Share2, Tag, X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import { ImageViewer } from '../viewer/ImageViewer';
import type { BrowsableItem, Metadata, ProjectDetail } from '../../types/api';

interface InfoPanelProps {
  metadata: Metadata | null;
  projectDetail?: ProjectDetail | null;
  selected?: BrowsableItem | null;
  loading?: boolean;
  onTagFilter?: (tag: string) => void;
  onDownload?: (item: BrowsableItem) => void;
  onShare?: (item: BrowsableItem) => void;
  onClose?: () => void;
}

function thumbnailUrlFor(path: string, size: number): string {
  const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
  return `/api/thumbnails/${encodedPath}?size=${size}`;
}

export function InfoPanel({ metadata, projectDetail, selected, loading, onTagFilter, onDownload, onShare, onClose }: InfoPanelProps) {
  const { t } = useI18n();
  const [viewerOpen, setViewerOpen] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const previewTriggerRef = useRef<HTMLButtonElement>(null);
  const detailTags = projectDetail?.tags ?? metadata?.tags;
  const detailNotes = projectDetail?.notes ?? metadata?.notes;
  const detailUrls = projectDetail?.urls ?? metadata?.urls;
  const externalUrls = detailUrls?.filter(url => {
    try {
      const protocol = new URL(url).protocol;
      return protocol === 'http:' || protocol === 'https:';
    } catch {
      return false;
    }
  }) ?? [];
  const isImage = selected?.category === 'images' || selected?.category === 'image' || /\.(jpe?g|png|gif|bmp|webp|tiff?|ico|svg|avif)$/i.test(selected?.extension ?? '');
  const projectImages = projectDetail?.images ?? [];
  const projectCoverIndex = projectDetail?.thumbnail_url
    ? Math.max(0, projectImages.findIndex(image => image.thumb_url === projectDetail.thumbnail_url))
    : 0;
  const previewUrl = projectDetail?.thumbnail_url
    ?? (selected && isImage ? thumbnailUrlFor(selected.path, 512) : null);
  const viewerImages = projectImages.length > 0
    ? projectImages.map(image => image.url)
    : projectDetail?.thumbnail_url
      ? [projectDetail.thumbnail_url]
    : selected && isImage
      ? [thumbnailUrlFor(selected.path, 2048)]
      : [];

  useEffect(() => {
    setPreviewError(false);
    setPreviewLoaded(false);
  }, [selected?.path]);

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
        {!selected && !metadata ? (
          <p className="mt-8 text-center text-xs text-slate-500">{t('info.no_selection')}</p>
        ) : (
          <div className="space-y-5">
            {previewUrl && selected && viewerImages.length > 0 && <button
              type="button"
              ref={previewTriggerRef}
              aria-label={`Open ${selected.name} preview`}
              onClick={() => setViewerOpen(true)}
              className="asset-preview-surface relative block aspect-video w-full overflow-hidden rounded bg-slate-900/60 text-left"
            >
              {!previewLoaded && !previewError && <span role="status" aria-label="Loading preview" className="absolute inset-0 flex items-center justify-center rounded text-xs text-slate-500">Loading preview</span>}
              {previewError ? (
                <span className="flex h-full w-full items-center justify-center rounded text-xs text-slate-500">Preview unavailable</span>
              ) : (
                <img src={previewUrl} alt={`${selected.name} preview`} draggable={false} onLoad={() => setPreviewLoaded(true)} onError={() => setPreviewError(true)} className={`${previewLoaded ? '' : 'opacity-0'} h-full w-full rounded object-contain`} />
              )}
            </button>}
            {loading ? (
              <div className="space-y-3" aria-label="Loading inspection details">
                <div className="skeleton h-4 w-3/4" />
                <div className="skeleton h-4 w-1/2" />
                <div className="skeleton h-4 w-2/3" />
              </div>
            ) : (
              <>
                {detailTags?.length ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><Tag size={14} /> {t('info.tags')}</div><div className="flex flex-wrap gap-1.5">{detailTags.map(tag => <button key={tag} type="button" onClick={() => onTagFilter?.(tag)} className="rounded-full border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300 hover:bg-indigo-500/20">{tag}</button>)}</div></div> : null}
                {detailNotes ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><FileText size={14} /> {t('info.notes')}</div><p className="whitespace-pre-wrap text-sm text-slate-300">{detailNotes}</p></div> : null}
                {externalUrls.length ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><LinkIcon size={14} /> {t('info.urls')}</div><div className="space-y-1">{externalUrls.map(url => <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="block truncate text-sm text-brand-400 hover:text-brand-300">{url}</a>)}</div></div> : null}
              </>
            )}
            {selected && <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-slate-700/50 pt-4 text-xs"><div><dt className="text-slate-500">Type</dt><dd className="mt-0.5 break-all text-slate-300">{selected.type === 'dir' ? 'Folder' : selected.extension || selected.category}</dd></div>{selected.size_fmt !== undefined && <div><dt className="text-slate-500">Size</dt><dd className="mt-0.5 text-slate-300">{selected.size_fmt}</dd></div>}{selected.modified !== undefined && <div><dt className="text-slate-500">Modified</dt><dd className="mt-0.5 text-slate-300">{new Date(selected.modified * 1000).toLocaleString()}</dd></div>}<div className="col-span-2"><dt className="text-slate-500">Path</dt><dd className="mt-0.5 break-all text-slate-300">{selected.path}</dd></div></dl>}
            {!loading && selected && (onDownload || onShare) && <div className="flex items-center gap-2 border-t border-slate-700/50 pt-4"><span className="text-xs text-slate-500">Actions</span>{onDownload && <button type="button" aria-label={t('action.download')} onClick={() => onDownload(selected)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><Download size={15} aria-hidden="true" /></button>}{onShare && <button type="button" aria-label={t('action.share')} onClick={() => onShare(selected)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><Share2 size={15} aria-hidden="true" /></button>}</div>}
          </div>
        )}
      </div>
      {viewerOpen && viewerImages.length > 0 && <ImageViewer
        images={viewerImages}
        currentIndex={projectCoverIndex}
        onClose={() => setViewerOpen(false)}
        restoreFocusRef={previewTriggerRef}
      />}
    </section>
  );
}
