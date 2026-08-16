import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { AppHeader } from '../components/layout/AppHeader';
import { ArrowLeft, Download, Tag, FileText, Link as LinkIcon, File } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useMetadataApi, useNotesApi } from '../hooks/usePageApis';
import { ApiError } from '../api/errors';
import type { ProjectDetail } from '../types/api';
import { ImageViewer } from '../components/viewer/ImageViewer';
import { Skeleton } from '../components/ui/Skeleton';
import { useI18n } from '../hooks/useI18n';
import { useTheme } from '../hooks/useTheme';
import { useInvalidation } from '../hooks/useInvalidation';
import { useToast } from '../components/ui/Toast';
import { useQuota } from '../hooks/useQuota';
import './DetailPage.css';

interface DetailPageProps {
  onOpenPalette?: () => void;
}

export default function DetailPage({ onOpenPalette }: DetailPageProps) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const path = searchParams.get('path') || '';
  const from = searchParams.get('from');
  const context = searchParams.get('context') || '';
  const { api, identityGeneration, capabilities } = useAuth();
  const metaApi = useMetadataApi();
  const notesApi = useNotesApi();
  const { t } = useI18n();
  const { showToast } = useToast();
  const { guardDownload, refresh: refreshQuota } = useQuota();
  const canEditMetadata = capabilities?.settings ?? false;
  useTheme();

  const [data, setData] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [notesDraft, setNotesDraft] = useState('');
  const [notesEditing, setNotesEditing] = useState(false);
  const [notesSaving, setNotesSaving] = useState(false);
  const detailGeneration = useRef(0);
  const detailAbort = useRef<AbortController | null>(null);
  const identityGenerationRef = useRef(identityGeneration);
  // Tracks the path the page is currently rendering so an in-flight notes save
  // for a previous path cannot commit state (data/toast/spinner) onto this one.
  const pathRef = useRef(path);
  pathRef.current = path;

  const refreshDetail = useCallback(() => {
    const generation = ++detailGeneration.current;
    detailAbort.current?.abort();
    const controller = new AbortController();
    detailAbort.current = controller;
    if (!path) {
      setData(null);
      setLoadError(false);
      setLoading(false);
      return () => controller.abort();
    }
    setLoading(true);
    setLoadError(false);
    metaApi.getProjectDetail(path, controller.signal)
      .then(detail => {
        if (!controller.signal.aborted && generation === detailGeneration.current) {
          setData(detail);
          setLoadError(false);
        }
      })
      .catch(err => {
        if (!controller.signal.aborted && generation === detailGeneration.current) {
          setData(null);
          // A 404 keeps the existing not-found state; any other failure is
          // surfaced as a load error with a retry action.
          setLoadError(!(err instanceof ApiError && err.status === 404));
        }
      })
      .finally(() => { if (!controller.signal.aborted && generation === detailGeneration.current) setLoading(false); });
    return () => controller.abort();
  }, [path, metaApi]);
  useEffect(() => refreshDetail(), [refreshDetail]);
  useEffect(() => {
    setNotesDraft(data?.notes ?? '');
    setNotesEditing(false);
  }, [data?.notes, path]);
  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    detailGeneration.current += 1;
    detailAbort.current?.abort();
    setData(null);
    setLoadError(false);
    setLoading(false);
    void refreshDetail();
  }, [identityGeneration, refreshDetail]);
  useInvalidation(['project_detail', 'metadata', 'tags'], event => {
    if (!event || event.paths.some(invalidatedPath => path === invalidatedPath || path.startsWith(`${invalidatedPath}/`) || invalidatedPath.startsWith(`${path}/`))) void refreshDetail();
  });

  const saveNotes = useCallback(async (next?: string) => {
    const value = next ?? notesDraft;
    if (!path || notesSaving) return;
    // Capture the path this save targets; a route change while the request is
    // in flight must not let the response commit onto the new path's state.
    const requestedPath = path;
    setNotesSaving(true);
    try {
      const saved = await notesApi.save(requestedPath, value);
      if (pathRef.current !== requestedPath) return;
      setData(prev => prev ? { ...prev, notes: saved.notes } : prev);
      setNotesEditing(false);
      showToast(t('info.notes_saved'), 'success');
    } catch {
      if (pathRef.current !== requestedPath) return;
      showToast(t('info.notes_save_failed'), 'error');
    } finally {
      // Only clear the flag if this is still the page that owns the request;
      // otherwise leave it for the new path's render cycle to handle.
      if (pathRef.current === requestedPath) setNotesSaving(false);
    }
  }, [notesApi, notesDraft, notesSaving, path, showToast, t]);

  const startQuotaDownload = useCallback((url: string) => {
    void (async () => {
      if (!await guardDownload()) return;
      window.open(url, '_blank', 'noopener,noreferrer');
      void refreshQuota();
    })();
  }, [guardDownload, refreshQuota]);

  const externalUrls = data?.urls?.filter(url => {
    try {
      const protocol = new URL(url).protocol;
      return protocol === 'http:' || protocol === 'https:';
    } catch {
      return false;
    }
  }) ?? [];

  const contextDestination = from === 'workspace'
    ? (context ? '/browse?path=' + encodeURIComponent(context) : '/browse')
    : (context ? '/gallery/collection?path=' + encodeURIComponent(context) : '/gallery');
  const backLabel = t('detail.back');

  return (
    <div className="detail-page">
      {onOpenPalette && (
        <AppHeader
          activeArea={from === 'workspace' ? 'workspace' : 'gallery'}
          galleryHref={from === 'workspace' && context ? '/gallery/collection?path=' + encodeURIComponent(context) : '/gallery'}
          workspaceHref={from === 'gallery' && context ? '/browse?path=' + encodeURIComponent(context) : '/browse'}
          contextNav={[{ to: contextDestination, label: backLabel, end: true }]}
          onOpenPalette={onOpenPalette}
        />
      )}
      {/* Top bar */}
      <div className="detail-toolbar">
        <button
          onClick={() => {
            if (from === 'gallery') navigate(context ? '/gallery/collection?path=' + encodeURIComponent(context) : '/gallery');
            else if (from === 'workspace') navigate(context ? '/browse?path=' + encodeURIComponent(context) : '/browse');
            else navigate(-1);
          }}
          className="detail-back-button"
        >
          <ArrowLeft size={20} /> {backLabel}
        </button>
        <div className="flex-1" />
        {data && (
          <a
            href={data.download_url}
            className="detail-download-button"
            onClick={event => {
              event.preventDefault();
              startQuotaDownload(data.download_url);
            }}
          >
            <Download size={16} /> {t('detail.download_all')}
          </a>
        )}
      </div>

      <div className="detail-content">
        {loading ? (
          <div className="space-y-4" role="status" aria-label={t('browse.loading')}>
            <Skeleton className="h-48 w-full rounded-xl" />
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : data ? (
          <>
            {/* Hero */}
            <div className="detail-hero">
              {data.thumbnail_url && (
                <img src={data.thumbnail_url} alt="" draggable={false} className="detail-hero-image" />
              )}
              <div className="detail-hero-overlay" />
              <div className="detail-hero-content">
                <span className="detail-eyebrow">{t('info.type')}</span>
                <h1>{data.name}</h1>
                <div className="detail-meta-row">
                  <span>{data.file_count} {t('detail.files')}</span>
                  <span>·</span>
                  <span>{data.total_size_fmt}</span>
                  {data.modified && (
                    <>
                      <span>·</span>
                      <span>{new Date(data.modified * 1000).toLocaleDateString()}</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Tags */}
            {data.tags && data.tags.length > 0 && (
              <div className="detail-section mb-6">
                <div className="detail-section-heading flex items-center gap-2 mb-3">
                  <Tag size={14} /> {t('info.tags')}
                </div>
                <div className="flex flex-wrap gap-2">
                  {data.tags.map(tag => (
                    <span key={tag} className="px-2.5 py-1 rounded-full text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Notes */}
            <div className="detail-section mb-6">
              <div className="detail-section-heading flex items-center gap-2 mb-2">
                <FileText size={14} /> {t('info.notes')}
                {canEditMetadata && !notesEditing && <button type="button" onClick={() => setNotesEditing(true)} className="ml-auto rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400 hover:border-indigo-500/50 hover:text-white">{t('info.edit_notes')}</button>}
              </div>
              {canEditMetadata && notesEditing ? (
                <div className="space-y-2">
                  <textarea value={notesDraft} onChange={event => setNotesDraft(event.target.value)} maxLength={4000} rows={5} placeholder={t('info.notes_placeholder')} aria-label={t('info.notes')} className="w-full rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-200 outline-none placeholder:text-slate-600 focus:border-indigo-500/50" />
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={() => void saveNotes()} disabled={notesSaving} className="rounded border border-indigo-500/30 px-3 py-1 text-xs text-indigo-300 disabled:cursor-not-allowed disabled:opacity-50">{t('info.save_notes')}</button>
                    <button type="button" onClick={() => { setNotesDraft(data.notes); setNotesEditing(false); }} disabled={notesSaving} className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-400 disabled:cursor-not-allowed disabled:opacity-50">{t('action.cancel')}</button>
                    {data.notes ? <button type="button" onClick={() => void saveNotes('')} disabled={notesSaving} className="ml-auto rounded border border-red-500/30 px-3 py-1 text-xs text-red-400 disabled:cursor-not-allowed disabled:opacity-50">{t('info.clear_notes')}</button> : null}
                  </div>
                </div>
              ) : data.notes ? (
                <p className="text-sm text-slate-300 whitespace-pre-wrap bg-slate-900/50 rounded-lg p-4 border border-slate-700/50">{data.notes}</p>
              ) : (
                <p className="text-xs text-slate-500">{t('info.no_notes')}</p>
              )}
            </div>

            {/* URLs */}
            {externalUrls.length > 0 && (
              <div className="detail-section mb-6">
              <div className="detail-section-heading flex items-center gap-2 mb-2">
                  <LinkIcon size={14} /> {t('info.urls')}
                </div>
                <div className="space-y-1">
                  {externalUrls.map((url, i) => (
                    <a key={i} href={url} target="_blank" rel="noopener noreferrer"
                      className="block text-sm text-indigo-400 hover:text-indigo-300 truncate transition-colors">
                      {url}
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Image Gallery */}
            {data.images && data.images.length > 0 && (
              <div className="detail-section detail-images-section mb-8">
                <h2 className="detail-section-title text-base font-semibold mb-3">{t('detail.images')}</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  {data.images.map((img, i) => (
                    <button
                      key={i}
                      onClick={() => setViewerIndex(i)}
                      className="aspect-square rounded-lg overflow-hidden border border-slate-700/50 hover:border-indigo-500/50 transition-colors bg-slate-900"
                    >
                      <img src={img.thumb_url} alt={img.name} draggable={false} loading="lazy" decoding="async" className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* File List */}
            {data.files && data.files.length > 0 && (
              <div className="detail-section detail-files-section">
                <h2 className="detail-section-title text-base font-semibold mb-3">{t('detail.files')} ({data.file_count})</h2>
                <div className="detail-file-table border border-slate-700/50 rounded-lg overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-700/50 bg-slate-800/50">
                        <th scope="col" className="text-left text-xs text-slate-500 font-medium px-4 py-2">{t('sort.name')}</th>
                        <th scope="col" className="text-left text-xs text-slate-500 font-medium px-4 py-2 w-24">{t('sort.size')}</th>
                        <th scope="col" className="text-left text-xs text-slate-500 font-medium px-4 py-2 w-20">{t('detail.action')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.files.map(file => {
                        const filePath = [data.path, file.name].filter(Boolean).join('/');
                        return (
                          <tr key={file.name} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                            <td className="px-4 py-2.5 text-sm text-slate-200 flex items-center gap-2">
                              <File size={14} className="text-slate-500 flex-shrink-0" />
                              <span className="truncate">{file.name}</span>
                            </td>
                            <td className="px-4 py-2.5 text-sm text-slate-400">{file.size_fmt}</td>
                            <td className="px-4 py-2.5">
                              <a
                                href={api.buildUrl(`download/${encodeURIComponent(filePath)}`)}
                                aria-label={t('browse.download_file_named', file.name)}
                                className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
                                onClick={event => {
                                  event.preventDefault();
                                  startQuotaDownload(api.buildUrl(`download/${encodeURIComponent(filePath)}`));
                                }}
                              >
                                <Download size={14} />
                              </a>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        ) : loadError ? (
          <div className="text-center mt-20 space-y-4">
            <p className="text-slate-500">{t('error.server')}</p>
            <button
              type="button"
              onClick={() => void refreshDetail()}
              className="rounded border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:border-indigo-500/50 hover:text-white transition-colors"
            >
              {t('gallery.retry')}
            </button>
          </div>
        ) : (
          <p className="text-slate-500 text-center mt-20">{t('error.not_found')}</p>
        )}
      </div>

      {viewerIndex !== null && data?.images && (
        <ImageViewer
          images={data.images.map(img => img.url)}
          currentIndex={viewerIndex}
          onClose={() => setViewerIndex(null)}
          onIndexChange={setViewerIndex}
        />
      )}
    </div>
  );
}
