import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Download, Tag, FileText, Link as LinkIcon, File } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { createMetadataApi } from '../api/metadata';
import type { ProjectDetail } from '../types/api';
import { ImageViewer } from '../components/viewer/ImageViewer';
import { Skeleton } from '../components/ui/Skeleton';
import { useI18n } from '../hooks/useI18n';
import { useTheme } from '../hooks/useTheme';
import { useInvalidation } from '../hooks/useInvalidation';

export default function DetailPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const path = searchParams.get('path') || '';
  const { api, identityGeneration } = useAuth();
  const metaApi = useMemo(() => createMetadataApi(api), [api]);
  const { t } = useI18n();
  useTheme();

  const [data, setData] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const detailGeneration = useRef(0);
  const detailAbort = useRef<AbortController | null>(null);
  const identityGenerationRef = useRef(identityGeneration);

  const refreshDetail = useCallback(() => {
    const generation = ++detailGeneration.current;
    detailAbort.current?.abort();
    const controller = new AbortController();
    detailAbort.current = controller;
    if (!path) {
      setData(null);
      setLoading(false);
      return () => controller.abort();
    }
    setLoading(true);
    metaApi.getProjectDetail(path, controller.signal)
      .then(detail => { if (!controller.signal.aborted && generation === detailGeneration.current) setData(detail); })
      .catch(() => { if (!controller.signal.aborted && generation === detailGeneration.current) setData(null); })
      .finally(() => { if (!controller.signal.aborted && generation === detailGeneration.current) setLoading(false); });
    return () => controller.abort();
  }, [path, metaApi]);
  useEffect(() => refreshDetail(), [refreshDetail]);
  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    detailGeneration.current += 1;
    detailAbort.current?.abort();
    setData(null);
    setLoading(false);
    void refreshDetail();
  }, [identityGeneration, refreshDetail]);
  useInvalidation(['project_detail', 'metadata', 'tags'], event => {
    if (!event || event.paths.some(invalidatedPath => path === invalidatedPath || path.startsWith(`${invalidatedPath}/`) || invalidatedPath.startsWith(`${path}/`))) void refreshDetail();
  });

  const externalUrls = data?.urls?.filter(url => {
    try {
      const protocol = new URL(url).protocol;
      return protocol === 'http:' || protocol === 'https:';
    } catch {
      return false;
    }
  }) ?? [];

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-4 h-14 border-b border-slate-700/50 bg-slate-900/50 backdrop-blur-sm">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={20} /> {t('detail.back')}
        </button>
        <div className="flex-1" />
        {data && (
          <a
            href={data.download_url}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-white bg-indigo-500 hover:bg-indigo-600 rounded-lg transition-colors"
          >
            <Download size={16} /> {t('detail.download_all')}
          </a>
        )}
      </div>

      <div className="p-6 max-w-5xl mx-auto">
        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-48 w-full rounded-xl" />
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : data ? (
          <>
            {/* Hero */}
            <div className="relative rounded-xl overflow-hidden bg-slate-900 border border-slate-700/50 mb-8">
              {data.thumbnail_url && (
                <img src={data.thumbnail_url} alt="" draggable={false} className="w-full h-48 object-cover opacity-50" />
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-slate-900 via-slate-900/60 to-transparent" />
              <div className="relative p-6">
                <h1 className="text-2xl font-bold text-white">{data.name}</h1>
                <div className="flex items-center gap-3 text-sm text-slate-400 mt-2">
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
              <div className="mb-6">
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-3">
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
            {data.notes && (
              <div className="mb-6">
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                  <FileText size={14} /> {t('info.notes')}
                </div>
                <p className="text-sm text-slate-300 whitespace-pre-wrap bg-slate-900/50 rounded-lg p-4 border border-slate-700/50">
                  {data.notes}
                </p>
              </div>
            )}

            {/* URLs */}
            {externalUrls.length > 0 && (
              <div className="mb-6">
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
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
              <div className="mb-8">
                <h2 className="text-base font-semibold text-white mb-3">{t('detail.images')}</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  {data.images.map((img, i) => (
                    <button
                      key={i}
                      onClick={() => setViewerIndex(i)}
                      className="aspect-square rounded-lg overflow-hidden border border-slate-700/50 hover:border-indigo-500/50 transition-colors bg-slate-900"
                    >
                      <img src={img.thumb_url} alt={img.name} draggable={false} className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* File List */}
            {data.files && data.files.length > 0 && (
              <div>
                <h2 className="text-base font-semibold text-white mb-3">{t('detail.files')} ({data.file_count})</h2>
                <div className="border border-slate-700/50 rounded-lg overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-700/50 bg-slate-800/50">
                        <th className="text-left text-xs text-slate-500 font-medium px-4 py-2">Name</th>
                        <th className="text-left text-xs text-slate-500 font-medium px-4 py-2 w-24">Size</th>
                        <th className="text-left text-xs text-slate-500 font-medium px-4 py-2 w-20">Action</th>
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
                            href={`/api/download/${encodeURIComponent(filePath)}`}
                            aria-label={`Download ${file.name}`}
                                className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
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
