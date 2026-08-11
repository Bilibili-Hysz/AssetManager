import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Download, FileText, Link as LinkIcon, Plus, Share2, Tag, X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import { useAuth } from '../../hooks/useAuth';
import { ImageViewer } from '../viewer/ImageViewer';
import type { BrowsableItem, Metadata, ProjectDetail } from '../../types/api';

interface InfoPanelProps {
  metadata: Metadata | null;
  projectDetail?: ProjectDetail | null;
  selected?: BrowsableItem | null;
  loading?: boolean;
  onTagFilter?: (tag: string) => void;
  onTagAdd?: (tag: string) => Promise<boolean> | boolean;
  onTagRemove?: (tag: string) => Promise<boolean> | boolean;
  tagMutationPending?: boolean;
  onDownload?: (item: BrowsableItem) => void;
  onShare?: (item: BrowsableItem) => void;
  onNotesSave?: (path: string, notes: string) => Promise<boolean>;
  canShare?: boolean;
  onClose?: () => void;
}

function thumbnailUrlFor(path: string, size: number, buildUrl: (path: string) => string): string {
  const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
  return buildUrl(`thumbnails/${encodedPath}?size=${size}`);
}

export function InfoPanel({
  metadata,
  projectDetail,
  selected,
  loading,
  onTagFilter,
  onTagAdd,
  onTagRemove,
  tagMutationPending = false,
  onDownload,
  onShare,
  onNotesSave,
  canShare = true,
  onClose,
}: InfoPanelProps) {
  const { t } = useI18n();
  const { api } = useAuth();
  const [viewerOpen, setViewerOpen] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [tagDraft, setTagDraft] = useState('');
  const [notesDraft, setNotesDraft] = useState('');
  const [notesEditing, setNotesEditing] = useState(false);
  const [notesSaving, setNotesSaving] = useState(false);
  const previewTriggerRef = useRef<HTMLButtonElement>(null);
  const detailTags = projectDetail?.tags ?? metadata?.tags ?? [];
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
  const isImage = selected?.category === 'images'
    || selected?.category === 'image'
    || /\.(jpe?g|png|gif|bmp|webp|tiff?|ico|svg|avif)$/i.test(selected?.extension ?? '');
  const projectImages = projectDetail?.images ?? [];
  const projectCoverIndex = projectDetail?.thumbnail_url
    ? Math.max(0, projectImages.findIndex(image => image.thumb_url === projectDetail.thumbnail_url))
    : 0;
  const previewUrl = projectDetail?.thumbnail_url
    ?? metadata?.thumbnail_url
    ?? (selected && isImage ? thumbnailUrlFor(selected.path, 512, api.buildUrl) : null);
  const viewerImages = projectImages.length > 0
    ? projectImages.map(image => image.url)
    : projectDetail?.thumbnail_url
      ? [projectDetail.thumbnail_url]
      : metadata?.thumbnail_url
        ? [metadata.thumbnail_url]
        : selected && isImage
          ? [thumbnailUrlFor(selected.path, 2048, api.buildUrl)]
          : [];

  useEffect(() => {
    setPreviewError(false);
    setPreviewLoaded(false);
    setTagDraft('');
    setNotesEditing(false);
  }, [selected?.path]);

  useEffect(() => {
    setNotesDraft(detailNotes ?? '');
  }, [detailNotes]);

  const saveNotes = async (next?: string) => {
    if (!selected || !onNotesSave || notesSaving) return;
    const value = next ?? notesDraft;
    setNotesSaving(true);
    try {
      const saved = await onNotesSave(selected.path, value);
      if (saved) setNotesEditing(false);
    } finally {
      setNotesSaving(false);
    }
  };

  const handleAddTag = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const tag = tagDraft.trim();
    if (!tag || !onTagAdd || tagMutationPending) return;
    if (await onTagAdd(tag)) setTagDraft('');
  };

  return (
    <section className="flex h-full flex-col" aria-label={t('info.title')}>
      <header className="flex items-center justify-between gap-2 border-b border-slate-700/50 px-4 py-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-200">{selected?.name ?? t('info.title')}</h3>
          {selected && <p className="text-xs text-slate-500">{selected.type === 'dir' ? t('info.folder') : selected.extension || selected.category}</p>}
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
                {selected && <div>
                  <div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><Tag size={14} /> {t('info.tags')}</div>
                  {detailTags.length > 0 ? <div className="flex flex-wrap gap-1.5">
                    {detailTags.map(tag => <span key={tag} className="inline-flex items-center rounded-full border border-indigo-500/20 bg-indigo-500/10 text-xs text-indigo-300">
                      <button type="button" onClick={() => onTagFilter?.(tag)} className="rounded-l-full px-2 py-0.5">{tag}</button>
                      {onTagRemove && <button type="button" onClick={() => void onTagRemove(tag)} disabled={tagMutationPending} aria-label={t('info.remove_tag', tag)} className="rounded-r-full px-1.5 py-0.5 text-indigo-300/70 disabled:cursor-not-allowed disabled:opacity-50"><X size={11} aria-hidden="true" /></button>}
                    </span>)}
                  </div> : <p className="text-xs text-slate-500">{t('info.no_tags')}</p>}
                  {onTagAdd && <form onSubmit={handleAddTag} className="mt-2 flex items-center gap-1.5">
                    <input value={tagDraft} onChange={event => setTagDraft(event.target.value)} placeholder={t('info.tag_placeholder')} aria-label={t('info.add_tag')} maxLength={200} disabled={tagMutationPending} className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-900/60 px-2 py-1 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-indigo-500/50" />
                    <button type="submit" disabled={!tagDraft.trim() || tagMutationPending} aria-label={t('info.add_tag')} className="rounded border border-indigo-500/30 p-1 text-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"><Plus size={14} aria-hidden="true" /></button>
                  </form>}
                </div>}
                {selected && onNotesSave ? <div>
                  <div className="mb-2 flex items-center gap-2 text-xs text-slate-500">
                    <FileText size={14} /> {t('info.notes')}
                    {!notesEditing && <button type="button" onClick={() => setNotesEditing(true)} className="ml-auto rounded border border-slate-700 px-1.5 py-0.5 text-xs text-slate-400 hover:border-indigo-500/50 hover:text-white">{t('info.edit_notes')}</button>}
                  </div>
                  {notesEditing ? <div className="space-y-2">
                    <textarea value={notesDraft} onChange={event => setNotesDraft(event.target.value)} maxLength={4000} rows={4} placeholder={t('info.notes_placeholder')} aria-label={t('info.notes')} className="w-full rounded border border-slate-700 bg-slate-900/60 p-2 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-indigo-500/50" />
                    <div className="flex items-center gap-1.5">
                      <button type="button" onClick={() => void saveNotes()} disabled={notesSaving} className="rounded border border-indigo-500/30 px-2 py-0.5 text-xs text-indigo-300 disabled:cursor-not-allowed disabled:opacity-50">{t('info.save_notes')}</button>
                      <button type="button" onClick={() => { setNotesDraft(detailNotes ?? ''); setNotesEditing(false); }} disabled={notesSaving} className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400 disabled:cursor-not-allowed disabled:opacity-50">{t('action.cancel')}</button>
                      {detailNotes ? <button type="button" onClick={() => void saveNotes('')} disabled={notesSaving} className="ml-auto rounded border border-red-500/30 px-2 py-0.5 text-xs text-red-400 disabled:cursor-not-allowed disabled:opacity-50">{t('info.clear_notes')}</button> : null}
                    </div>
                  </div> : detailNotes ? <p className="whitespace-pre-wrap text-sm text-slate-300">{detailNotes}</p> : <p className="text-xs text-slate-500">{t('info.no_notes')}</p>}
                </div> : detailNotes ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><FileText size={14} /> {t('info.notes')}</div><p className="whitespace-pre-wrap text-sm text-slate-300">{detailNotes}</p></div> : null}
                {externalUrls.length ? <div><div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><LinkIcon size={14} /> {t('info.urls')}</div><div className="space-y-1">{externalUrls.map(url => <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="block truncate text-sm text-brand-400 hover:text-brand-300">{url}</a>)}</div></div> : null}
              </>
            )}
            {selected && <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-slate-700/50 pt-4 text-xs"><div><dt className="text-slate-500">{t('info.type')}</dt><dd className="mt-0.5 break-all text-slate-300">{selected.type === 'dir' ? t('info.folder') : selected.extension || selected.category}</dd></div>{selected.size_fmt !== undefined && <div><dt className="text-slate-500">{t('info.size')}</dt><dd className="mt-0.5 text-slate-300">{selected.size_fmt}</dd></div>}{selected.modified !== undefined && <div><dt className="text-slate-500">{t('info.modified')}</dt><dd className="mt-0.5 text-slate-300">{new Date(selected.modified * 1000).toLocaleString()}</dd></div>}<div className="col-span-2"><dt className="text-slate-500">{t('info.path')}</dt><dd className="mt-0.5 break-all text-slate-300">{selected.path}</dd></div></dl>}
            {!loading && selected && (onDownload || (onShare && canShare)) && <div className="flex items-center gap-2 border-t border-slate-700/50 pt-4"><span className="text-xs text-slate-500">{t('action.actions')}</span>{onDownload && <button type="button" aria-label={t('action.download')} onClick={() => onDownload(selected)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><Download size={15} aria-hidden="true" /></button>}{onShare && canShare && <button type="button" aria-label={t('action.share')} onClick={() => onShare(selected)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><Share2 size={15} aria-hidden="true" /></button>}</div>}
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
