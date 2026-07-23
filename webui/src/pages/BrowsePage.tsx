import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Download, Share2, Copy, Eye } from 'lucide-react';
import { AppLayout } from '../components/layout/AppLayout';
import { Header } from '../components/layout/Header';
import { Sidebar } from '../components/layout/Sidebar';
import { InfoPanel } from '../components/layout/InfoPanel';
import { Breadcrumb } from '../components/files/Breadcrumb';
import { FileToolbar } from '../components/files/FileToolbar';
import { ProjectGrid } from '../components/files/ProjectGrid';
import { ProjectList } from '../components/files/ProjectList';
import { ContextMenu } from '../components/ui/ContextMenu';
import { Skeleton } from '../components/ui/Skeleton';
import { ShareDialog } from '../components/shares/ShareDialog';
import { useAuth } from '../hooks/useAuth';
import { useWebSocket } from '../hooks/useWebSocket';
import { useProjects } from '../hooks/useProjects';
import { useThumbnailCache } from '../hooks/useThumbnailCache';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { createFilesApi } from '../api/files';
import { createMetadataApi } from '../api/metadata';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';
import { useDownloadProgress } from '../components/ui/DownloadProgress';
import type { BrowsableItem, Metadata } from '../types/api';

export default function BrowsePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialPath = searchParams.get('path') || '';
  const { data, isLoading, error, currentPath, sort, navigateTo, setSort, refresh, listingGeneration, hydrateDirectories } = useProjects(initialPath);
  const { loadThumbnails, getThumbnail, revision: thumbnailRevision } = useThumbnailCache();
  const { api, user } = useAuth();
  const filesApi = useMemo(() => createFilesApi(api), [api]);
  const metaApi = useMemo(() => createMetadataApi(api), [api]);
  const { t } = useI18n();
  const { showToast } = useToast();
  const downloadProgress = useDownloadProgress();
  const isMobile = useMediaQuery('(max-width: 768px)');

  const [viewMode, setViewMode] = useState<'grid' | 'list'>(() => {
    try { return (localStorage.getItem('am_view') as 'grid' | 'list') || 'grid'; } catch { return 'grid'; }
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: BrowsableItem; trigger?: HTMLElement } | null>(null);
  const [sharePaths, setSharePaths] = useState<string[] | null>(null);
  const [shareDialogTrigger, setShareDialogTrigger] = useState<HTMLElement | null | undefined>(undefined);
  const [selectedMetadata, setSelectedMetadata] = useState<Metadata | null>(null);
  const [selectedItem, setSelectedItem] = useState<BrowsableItem | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [tagResults, setTagResults] = useState<BrowsableItem[] | null>(null);
  const [isDownloadInFlight, setIsDownloadInFlight] = useState(false);

  // ── Sidebar / Info panel state ──
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try { return localStorage.getItem('am_sidebar_open') !== 'false'; } catch { return true; }
  });
  const [infoOpen, setInfoOpen] = useState(() => {
    try { return localStorage.getItem('am_info_open') !== 'false'; } catch { return true; }
  });
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try { return parseInt(localStorage.getItem('am_sidebar_w') || '260', 10); } catch { return 260; }
  });
  const [infoWidth, setInfoWidth] = useState(() => {
    try { return parseInt(localStorage.getItem('am_info_w') || '320', 10); } catch { return 320; }
  });

  // Persist widths
  useEffect(() => { try { localStorage.setItem('am_sidebar_w', String(sidebarWidth)); } catch {} }, [sidebarWidth]);
  useEffect(() => { try { localStorage.setItem('am_info_w', String(infoWidth)); } catch {} }, [infoWidth]);

  // ── Drag refs (no re-renders during drag) ──
  const sidebarDrag = useRef(false);
  const sidebarStartX = useRef(0);
  const sidebarStartW = useRef(0);
  const infoDrag = useRef(false);
  const infoStartX = useRef(0);
  const infoStartW = useRef(0);
  const rafId = useRef<number | null>(null);
  const tagSearchGeneration = useRef(0);
  const downloadInFlight = useRef(false);
  const metadataGeneration = useRef(0);
  const metadataAbort = useRef<AbortController | null>(null);
  const summaryAbort = useRef<AbortController | null>(null);
  const summaryPaths = useRef(new Set<string>());
  const summaryPending = useRef<string[]>([]);
  const summaryFlushScheduled = useRef(false);

  useEffect(() => () => {
    tagSearchGeneration.current += 1;
    metadataGeneration.current += 1;
    metadataAbort.current?.abort();
    summaryAbort.current?.abort();
  }, []);

  useEffect(() => {
    summaryAbort.current?.abort();
    summaryAbort.current = new AbortController();
    summaryPaths.current.clear();
    summaryPending.current = [];
    summaryFlushScheduled.current = false;
  }, [listingGeneration]);

  const handleDirectoryVisible = useCallback((path: string) => {
    if (!path || summaryPaths.current.has(path)) return;
    summaryPaths.current.add(path);
    summaryPending.current.push(path);
    if (summaryFlushScheduled.current) return;
    summaryFlushScheduled.current = true;
    queueMicrotask(async () => {
      try {
        while (summaryPending.current.length) {
          const paths = summaryPending.current.splice(0, 48);
          const controller = summaryAbort.current;
          if (!controller || controller.signal.aborted) return;
          await hydrateDirectories(paths, controller.signal, listingGeneration);
        }
      } catch {
        // A later visibility event can retry; do not spin on a failed request.
      } finally {
        summaryFlushScheduled.current = false;
      }
    });
  }, [hydrateDirectories, listingGeneration]);

  // WebSocket real-time updates
  useWebSocket({
    onEvent: (type) => {
      if (type === 'file_changed' || type === 'file_added' || type === 'file_removed') {
        refresh();
      }
    },
    enabled: Boolean(user),
  });

  useEffect(() => {
    const requestedPath = searchParams.get('path') || '';
    if (requestedPath !== currentPath) {
      tagSearchGeneration.current += 1;
      metadataGeneration.current += 1;
      metadataAbort.current?.abort();
      setActiveTag(null);
      setTagResults(null);
      navigateTo(requestedPath);
    }
  }, [currentPath, navigateTo, searchParams]);

  const handleSidebarDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    sidebarDrag.current = true;
    sidebarStartX.current = e.clientX;
    sidebarStartW.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [sidebarWidth]);

  const handleInfoDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    infoDrag.current = true;
    infoStartX.current = e.clientX;
    infoStartW.current = infoWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [infoWidth]);

  useEffect(() => {
    const handleMove = (e: MouseEvent) => {
      if (rafId.current) return;
      rafId.current = requestAnimationFrame(() => {
        rafId.current = null;
        if (sidebarDrag.current) {
          setSidebarWidth(Math.max(150, Math.min(e.clientX, 400)));
        }
        if (infoDrag.current) {
          setInfoWidth(Math.max(200, Math.min(window.innerWidth - e.clientX, 400)));
        }
      });
    };
    const handleUp = () => {
      sidebarDrag.current = false;
      infoDrag.current = false;
      if (rafId.current) { cancelAnimationFrame(rafId.current); rafId.current = null; }
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    return () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
      if (rafId.current) cancelAnimationFrame(rafId.current);
    };
  }, []);

  // ── Handlers ──
  const handleNavigate = useCallback((path: string) => {
    tagSearchGeneration.current += 1;
    metadataGeneration.current += 1;
    metadataAbort.current?.abort();
    navigateTo(path);
    setSearchParams(path ? { path } : {}, { replace: true });
    setSelected(new Set());
    setSelectedItem(null);
    setSelectedMetadata(null);
    setActiveTag(null);
    setTagResults(null);
  }, [navigateTo, setSearchParams]);

  const handleNavigateDetail = useCallback((path: string) => {
    tagSearchGeneration.current += 1;
    navigate(`/detail?path=${encodeURIComponent(path)}`);
  }, [navigate]);

  const handleViewModeChange = useCallback((mode: 'grid' | 'list') => {
    setViewMode(mode);
    try { localStorage.setItem('am_view', mode); } catch {}
  }, []);

  const handleSelect = useCallback((path: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const handleCardClick = useCallback((item: BrowsableItem) => {
    const generation = ++metadataGeneration.current;
    metadataAbort.current?.abort();
    const abortController = new AbortController();
    metadataAbort.current = abortController;
    setSelectedItem(item);
    setMetadataLoading(true);
    metaApi.getMeta(item.path, abortController.signal)
      .then(metadata => {
        if (generation === metadataGeneration.current) setSelectedMetadata(metadata);
      })
      .catch(() => {
        if (generation === metadataGeneration.current) setSelectedMetadata(null);
      })
      .finally(() => {
        if (generation === metadataGeneration.current) setMetadataLoading(false);
      });
  }, [metaApi]);

  const handleInspect = useCallback((item: BrowsableItem) => {
    if (isMobile) handleNavigateDetail(item.path);
    else handleCardClick(item);
  }, [handleCardClick, handleNavigateDetail, isMobile]);

  const handleCardDoubleClick = useCallback((item: BrowsableItem) => {
    handleNavigateDetail(item.path);
  }, [handleNavigateDetail]);

  const handleContextMenu = useCallback((e: React.MouseEvent, item: BrowsableItem) => {
    e.preventDefault();
    const trigger = e.type === 'click' ? e.currentTarget as HTMLElement : undefined;
    const rect = e.currentTarget.getBoundingClientRect();
    setContextMenu({
      x: e.clientX || rect.right,
      y: e.clientY || rect.bottom,
      item,
      trigger,
    });
  }, []);

  const handleDownload = useCallback((path: string) => {
    filesApi.download(path);
  }, [filesApi]);

  const handleInfoDownload = useCallback((item: BrowsableItem) => {
    handleDownload(item.path);
  }, [handleDownload]);

  const handleInfoShare = useCallback((item: BrowsableItem) => {
    setShareDialogTrigger(document.activeElement instanceof HTMLElement ? document.activeElement : undefined);
    setSharePaths([item.path]);
  }, []);

  const handleCopyPath = useCallback((path: string) => {
    navigator.clipboard.writeText(path).catch(() => {});
  }, []);

  const handleTagFilter = useCallback((tag: string) => {
    const generation = ++tagSearchGeneration.current;
    setActiveTag(tag);
    setSelected(new Set());
    setTagResults(null);
    metaApi.search('', tag).then(res => {
      if (generation === tagSearchGeneration.current) {
        setTagResults(res.results);
      }
    }).catch(() => {
      if (generation === tagSearchGeneration.current) {
        setActiveTag(null);
        setTagResults(null);
        showToast('Failed to filter by tag', 'error');
      }
    });
  }, [metaApi, showToast]);

  const handleClearTagFilter = useCallback(() => {
    tagSearchGeneration.current += 1;
    setActiveTag(null);
    setTagResults(null);
  }, []);

  const handleDownloadSelected = useCallback(async () => {
    const paths = Array.from(selected);
    if (paths.length === 0 || downloadInFlight.current) return;
    downloadInFlight.current = true;
    setIsDownloadInFlight(true);
    downloadProgress.start();
    try {
      await filesApi.batchDownload(paths, downloadProgress.update);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to download ZIP archive', 'error');
    } finally {
      downloadProgress.finish();
      downloadInFlight.current = false;
      setIsDownloadInFlight(false);
    }
  }, [downloadProgress, filesApi, selected, showToast]);

  const handleSidebarToggle = useCallback(() => {
    if (isMobile) {
      setInfoOpen(false);
      try { localStorage.setItem('am_info_open', '0'); } catch {}
    }
    setSidebarOpen(prev => {
      const next = !prev;
      try { localStorage.setItem('am_sidebar_open', next ? '1' : '0'); } catch {}
      return next;
    });
  }, [isMobile, sidebarOpen]);

  const handleInfoToggle = useCallback(() => {
    if (isMobile) {
      setSidebarOpen(false);
      try { localStorage.setItem('am_sidebar_open', '0'); } catch {}
    }
    setInfoOpen(prev => {
      const next = !prev;
      try { localStorage.setItem('am_info_open', next ? '1' : '0'); } catch {}
      return next;
    });
  }, [infoOpen, isMobile]);

  // ── Thumbnails ──
  const visibleItems = tagResults ?? data?.items ?? [];
  const imagePaths = useMemo(() => visibleItems
    .filter(item => item.category === 'image' || /\.(jpg|jpeg|png|gif|webp)$/i.test(item.extension))
    .map(item => item.path), [visibleItems]);
  useEffect(() => {
    if (viewMode === 'grid') void loadThumbnails(imagePaths);
  }, [imagePaths, loadThumbnails, viewMode]);
  const thumbnailMap = useMemo(() => {
    const thumbnails: Record<string, string> = {};
    if (viewMode === 'grid') {
      imagePaths.forEach(path => {
        const thumbnail = getThumbnail(path);
        if (thumbnail) thumbnails[path] = `data:image/jpeg;base64,${thumbnail}`;
      });
    }
    return thumbnails;
  }, [getThumbnail, imagePaths, thumbnailRevision, viewMode]);

  useEffect(() => {
    const handleWorkspaceShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isEditable = target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable;
      if (isEditable || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;

      if (event.key === 'g') {
        event.preventDefault();
        handleViewModeChange(viewMode === 'grid' ? 'list' : 'grid');
      } else if (event.key === 's') {
        event.preventDefault();
        setSelectMode(current => !current);
        setSelected(new Set());
      } else if (event.key === 'Escape') {
        if (activeTag) {
          event.preventDefault();
          handleClearTagFilter();
        } else if (selected.size > 0) {
          event.preventDefault();
          setSelected(new Set());
        } else if (isMobile && (sidebarOpen || infoOpen)) {
          event.preventDefault();
          if (infoOpen) handleInfoToggle();
          else handleSidebarToggle();
        }
      }
    };

    document.addEventListener('keydown', handleWorkspaceShortcut);
    return () => document.removeEventListener('keydown', handleWorkspaceShortcut);
  }, [activeTag, handleClearTagFilter, handleInfoToggle, handleSidebarToggle, handleViewModeChange, infoOpen, isMobile, selected.size, sidebarOpen, viewMode]);

  return (
    <AppLayout
      header={
        <Header
          onSidebarToggle={handleSidebarToggle}
          onInfoToggle={handleInfoToggle}
          sidebarOpen={sidebarOpen}
          infoOpen={infoOpen}
        />
      }
      sidebar={<Sidebar onNavigate={handleNavigate} currentPath={currentPath} />}
        infoPanel={<InfoPanel metadata={selectedMetadata} selected={selectedItem} loading={metadataLoading} onTagFilter={handleTagFilter} onDownload={handleInfoDownload} onShare={handleInfoShare} onClose={handleInfoToggle} />}
      sidebarOpen={sidebarOpen}
      infoOpen={infoOpen}
      sidebarWidth={sidebarWidth}
      infoWidth={infoWidth}
      onSidebarDragStart={handleSidebarDragStart}
      onInfoDragStart={handleInfoDragStart}
      onSidebarToggle={handleSidebarToggle}
      onInfoToggle={handleInfoToggle}
      onViewModeToggle={() => handleViewModeChange(viewMode === 'grid' ? 'list' : 'grid')}
      viewMode={viewMode}
      selectMode={selectMode}
      onSelectModeToggle={() => {
        setSelectMode(prev => !prev);
        setSelected(new Set());
      }}
    >
      <Breadcrumb path={currentPath} onNavigate={handleNavigate} />

      <FileToolbar
        sort={sort}
        onSortChange={setSort}
        viewMode={viewMode}
        onViewModeChange={handleViewModeChange}
        selectedCount={selected.size}
        onDownloadSelected={handleDownloadSelected}
        isDownloadInFlight={isDownloadInFlight}
        activeTag={activeTag}
        onClearTag={handleClearTagFilter}
      />

      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 p-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-slate-700/50 overflow-hidden">
              <Skeleton className="aspect-square rounded-none" />
              <div className="p-2.5 space-y-1.5">
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3 w-1/3" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
          <p className="text-base">{t('browse.error')}</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      ) : visibleItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
          <p className="text-base">{t('browse.empty')}</p>
        </div>
      ) : viewMode === 'grid' ? (
        <ProjectGrid
          items={visibleItems}
          selected={selected}
          onSelect={handleSelect}
          onZipSelect={handleSelect}
          onInspect={handleInspect}
          onNavigate={handleNavigate}
          selectionMode={selectMode}
          onDoubleClick={handleCardDoubleClick}
          onContextMenu={handleContextMenu}
          thumbnailMap={thumbnailMap}
          onDirectoryVisible={handleDirectoryVisible}
        />
      ) : (
        <ProjectList
          items={visibleItems}
          selected={selected}
          onSelect={handleSelect}
          onZipSelect={handleSelect}
          onInspect={handleInspect}
          onNavigate={handleNavigate}
          selectionMode={selectMode}
          onDoubleClick={handleCardDoubleClick}
          onContextMenu={handleContextMenu}
          onDirectoryVisible={handleDirectoryVisible}
        />
      )}

      {/* Context Menu */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          trigger={contextMenu.trigger}
          onClose={() => setContextMenu(null)}
          items={[
            { label: t('action.download'), icon: <Download size={13} />, onClick: () => handleDownload(contextMenu.item.path) },
            ...(contextMenu.item.type === 'dir' ? [] : [{ label: t('action.detail'), icon: <Eye size={13} />, onClick: () => handleNavigateDetail(contextMenu.item.path) }]),
            { label: t('action.share'), icon: <Share2 size={13} />, onClick: () => {
              setShareDialogTrigger(contextMenu?.trigger);
              setSharePaths([contextMenu.item.path]);
            }},
            { label: t('action.copy_path'), icon: <Copy size={13} />, onClick: () => handleCopyPath(contextMenu.item.path) },
          ]}
        />
      )}

      {/* Share Dialog */}
      {sharePaths && (
        <ShareDialog
          open={true}
          onClose={() => {
            setSharePaths(null);
            setShareDialogTrigger(undefined);
          }}
          paths={sharePaths}
          returnFocusTo={shareDialogTrigger}
        />
      )}
    </AppLayout>
  );
}
