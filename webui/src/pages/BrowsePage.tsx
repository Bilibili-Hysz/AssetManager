import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Download, Share2, Copy, Eye, Link2, X } from 'lucide-react';
import { AppLayout } from '../components/layout/AppLayout';
import { Header } from '../components/layout/Header';
import { AppHeader } from '../components/layout/AppHeader';
import { Sidebar } from '../components/layout/Sidebar';
import { InfoPanel } from '../components/layout/InfoPanel';
import { Breadcrumb } from '../components/files/Breadcrumb';
import { FileToolbar } from '../components/files/FileToolbar';
import { ProjectGrid } from '../components/files/ProjectGrid';
import { ProjectList } from '../components/files/ProjectList';
import { MasonryView } from '../components/files/MasonryView';
import { ContextMenu } from '../components/ui/ContextMenu';
import { Skeleton } from '../components/ui/Skeleton';
import { ShareDialog } from '../components/shares/ShareDialog';
import { useAuth } from '../hooks/useAuth';
import { useCachedQuery } from '../hooks/useCachedQuery';
import { useInvalidation } from '../hooks/useInvalidation';
import { useProjects } from '../hooks/useProjects';
import { useThumbnailCache } from '../hooks/useThumbnailCache';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { createFilesApi } from '../api/files';
import { createMetadataApi } from '../api/metadata';
import { createTagsApi } from '../api/tags';
import { createNotesApi } from '../api/notes';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';
import { useDownloadProgress } from '../components/ui/DownloadProgress';
import { useQuota } from '../hooks/useQuota';
import { triggerBlobDownload } from '../utils/download';
import type { BrowsableItem, Metadata, ProjectDetail, SearchResponse } from '../types/api';

interface BrowsePageProps {
  onOpenPalette?: () => void;
}

/** The inspected-item query discriminates by the browsed entry's kind. */
type SelectedDetail =
  | { kind: 'dir'; detail: ProjectDetail }
  | { kind: 'file'; meta: Metadata };

export default function BrowsePage({ onOpenPalette }: BrowsePageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialPath = searchParams.get('path') || '';
  const { data, isLoading, error, currentPath, sort, navigateTo, setSort, refresh, listingGeneration, hydrateDirectories } = useProjects(initialPath);
  const { loadThumbnails, getThumbnail, revision: thumbnailRevision } = useThumbnailCache();
  const { api, identityGeneration, capabilities } = useAuth();
  const filesApi = useMemo(() => createFilesApi(api), [api]);
  const metaApi = useMemo(() => createMetadataApi(api), [api]);
  const tagsApi = useMemo(() => createTagsApi(api), [api]);
  const notesApi = useMemo(() => createNotesApi(api), [api]);
  const { t } = useI18n();
  const { showToast } = useToast();
  const canEditMetadata = capabilities?.settings ?? false;
  const downloadProgress = useDownloadProgress();
  const { guardDownload, refresh: refreshQuota } = useQuota();
  const isMobile = useMediaQuery('(max-width: 768px)');

  const [viewMode, setViewMode] = useState<'grid' | 'list' | 'masonry'>(() => {
    try {
      const stored = localStorage.getItem('am_view');
      return stored === 'grid' || stored === 'list' || stored === 'masonry' ? stored : 'grid';
    } catch { return 'grid'; }
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: BrowsableItem; trigger?: HTMLElement } | null>(null);
  const [sharePaths, setSharePaths] = useState<string[] | null>(null);
  const [shareDialogTrigger, setShareDialogTrigger] = useState<HTMLElement | null | undefined>(undefined);
  const [selectedItem, setSelectedItem] = useState<BrowsableItem | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [isDownloadInFlight, setIsDownloadInFlight] = useState(false);
  const [tagMutationPending, setTagMutationPending] = useState(false);
  const [tagsRefreshKey, setTagsRefreshKey] = useState(0);

  // ── Sidebar / Info panel state ──
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try { return localStorage.getItem('am_sidebar_open') !== 'false'; } catch { return true; }
  });
  const [infoOpen, setInfoOpen] = useState(() => {
    try { return localStorage.getItem('am_info_open') !== 'false'; } catch { return true; }
  });
  const desktopPanelsRef = useRef({ sidebar: sidebarOpen, info: infoOpen });
  const wasMobileRef = useRef(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try { return parseInt(localStorage.getItem('am_sidebar_w') || '260', 10); } catch { return 260; }
  });
  const [infoWidth, setInfoWidth] = useState(() => {
    try { return parseInt(localStorage.getItem('am_info_w') || '320', 10); } catch { return 320; }
  });

  useEffect(() => {
    if (isMobile) {
      if (!wasMobileRef.current) {
        desktopPanelsRef.current = { sidebar: sidebarOpen, info: infoOpen };
        setSidebarOpen(false);
        setInfoOpen(false);
        try {
          localStorage.setItem('am_sidebar_open', '0');
          localStorage.setItem('am_info_open', '0');
        } catch {}
      }
    } else if (wasMobileRef.current) {
      const desktopPanels = desktopPanelsRef.current;
      setSidebarOpen(desktopPanels.sidebar);
      setInfoOpen(desktopPanels.info);
      try {
        localStorage.setItem('am_sidebar_open', desktopPanels.sidebar ? '1' : '0');
        localStorage.setItem('am_info_open', desktopPanels.info ? '1' : '0');
      } catch {}
    }
    wasMobileRef.current = isMobile;
  }, [isMobile]);

  // Persist widths
  useEffect(() => { try { localStorage.setItem('am_sidebar_w', String(sidebarWidth)); } catch {} }, [sidebarWidth]);
  useEffect(() => { try { localStorage.setItem('am_info_w', String(infoWidth)); } catch {} }, [infoWidth]);

  // ── Drag refs (no re-renders during drag) ──
  const sidebarDrag = useRef(false);
  const sidebarStartX = useRef(0);
  const sidebarStartW = useRef(0);
  const infoDrag = useRef(false);
  const infoStartX = useRef(0);
  const lastManualRefreshRef = useRef(0);
  const infoStartW = useRef(0);
  const rafId = useRef<number | null>(null);
  const downloadInFlight = useRef(false);
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const summaryAbort = useRef<AbortController | null>(null);
  const summaryPaths = useRef(new Set<string>());
  const summaryPending = useRef<string[]>([]);
  const summaryFlushScheduled = useRef(false);
  const identityGenerationRef = useRef(identityGeneration);

  // ── Cached tag search + inspected-item detail ──
  // Both flows fetch through useCachedQuery but register NO invalidation
  // domains of their own: the page-level useInvalidation below owns the
  // 1.5s manual-refresh suppression window, which must cover them too.
  const activeTagRef = useRef(activeTag);
  activeTagRef.current = activeTag;
  const selectedItemRef = useRef(selectedItem);
  selectedItemRef.current = selectedItem;
  // Per-trigger failure policy: a user-initiated filter resets the filter
  // and toasts on failure; background re-searches stay silent.
  const tagSearchFailureHandlingRef = useRef({ resetFilterOnFailure: false, notifyOnFailure: false });

  const { data: tagData, error: tagError, isFetching: tagFetching, refresh: refreshTagSearch } = useCachedQuery<SearchResponse>({
    key: ['tag-search', activeTag ?? ''],
    queryFn: signal => metaApi.search('', activeTag ?? '', undefined, signal),
    enabled: activeTag !== null,
  });

  const { data: selectedData, isFetching: selectedFetching, refresh: refreshSelectedQuery, setData: setSelectedData } = useCachedQuery<SelectedDetail>({
    key: ['item-metadata', selectedItem?.path ?? '', selectedItem?.type ?? ''],
    queryFn: signal => {
      const item = selectedItem;
      if (!item) return Promise.reject(new Error('no item selected'));
      return item.type === 'dir'
        ? metaApi.getProjectDetail(item.path, signal).then(detail => ({ kind: 'dir' as const, detail }))
        : metaApi.getMeta(item.path, signal).then(meta => ({ kind: 'file' as const, meta }));
    },
    enabled: selectedItem !== null,
  });

  // Derived views: a key change (new tag / new item) resets data to
  // undefined, mirroring the old explicit clears; a failed first fetch
  // leaves data undefined so the panels fall back like before.
  const selectedMetadata = selectedData?.kind === 'file' ? selectedData.meta : null;
  const selectedProjectDetail = selectedData?.kind === 'dir' ? selectedData.detail : null;
  const metadataLoading = selectedItem !== null && selectedFetching;
  // SearchResult widens to BrowsableItem (the optional fields are all
  // partial), matching how the pre-cache flow stored these results.
  const tagResults: BrowsableItem[] | null = activeTag !== null ? (tagData?.results ?? null) : null;
  const tagLoading = activeTag !== null && tagFetching;

  // Tag-search failure policy (see tagSearchFailureHandlingRef).
  useEffect(() => {
    if (tagError == null) return;
    const handling = tagSearchFailureHandlingRef.current;
    if (handling.resetFilterOnFailure) {
      setActiveTag(null);
      setSearchParams(currentPath ? { path: currentPath } : {}, { replace: true });
    }
    if (handling.notifyOnFailure) showToast(t('info.tag_filter_failed'), 'error');
  }, [tagError, currentPath, setSearchParams, showToast, t]);

  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    setSelected(new Set());
    setSelectedItem(null);
    setActiveTag(null);
  }, [identityGeneration]);

  useEffect(() => () => {
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

  useEffect(() => {
    const requestedPath = searchParams.get('path') || '';
    if (searchParams.get('tag')) return;
    if (requestedPath !== currentPath) {
      setActiveTag(null);
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

  const handleNavigate = useCallback((path: string) => {
    setActiveTag(null);
    navigateTo(path);
    setSearchParams(path ? { path } : {}, { replace: true });
    setSelected(new Set());
    setSelectedItem(null);
  }, [navigateTo, setSearchParams]);

  const handleNavigateDetail = useCallback((path: string) => {
    navigate(`/detail?path=${encodeURIComponent(path)}`);
  }, [navigate]);

  const handleViewModeChange = useCallback((mode: 'grid' | 'list' | 'masonry') => {
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
    setSelectedItem(item);
    // A different card switches the cache key and fetches on its own; a
    // re-click on the same card re-inspects it (abort + refetch, as the
    // pre-cache flow did).
    const current = selectedItemRef.current;
    if (current && current.path === item.path && current.type === item.type) {
      refreshSelectedQuery();
    }
  }, [refreshSelectedQuery]);

  const refreshSelected = useCallback(() => {
    if (selectedItem) refreshSelectedQuery();
  }, [refreshSelectedQuery, selectedItem]);

  const handleNotesSave = useCallback(async (notesPath: string, notes: string): Promise<boolean> => {
    try {
      const saved = await notesApi.save(notesPath, notes);
      // Local optimistic patch on the cached entry; the projection event
      // will confirm it via a background refetch.
      setSelectedData(prev => {
        if (!prev) return prev;
        if (prev.kind === 'dir' && prev.detail.path === notesPath) {
          return { kind: 'dir', detail: { ...prev.detail, notes: saved.notes } };
        }
        if (prev.kind === 'file' && prev.meta.path === notesPath) {
          return { kind: 'file', meta: { ...prev.meta, notes: saved.notes } };
        }
        return prev;
      });
      showToast(t('info.notes_saved'), 'success');
      return true;
    } catch {
      showToast(t('info.notes_save_failed'), 'error');
      return false;
    }
  }, [notesApi, setSelectedData, showToast, t]);

  const runTagSearch = useCallback(
    (tag: string, options: { clearResults: boolean; resetFilterOnFailure: boolean; notifyOnFailure: boolean }) => {
      tagSearchFailureHandlingRef.current = {
        resetFilterOnFailure: options.resetFilterOnFailure,
        notifyOnFailure: options.notifyOnFailure,
      };
      // A new tag switches the cache key and fetches on its own; re-searching
      // the active tag refreshes the existing entry in place.
      if (activeTagRef.current === tag) refreshTagSearch();
    },
    [refreshTagSearch],
  );

  const mutateSelectedTag = useCallback(async (tag: string, action: 'add' | 'remove') => {
    if (!selectedItem || tagMutationPending) return false;
    setTagMutationPending(true);
    try {
      if (action === 'add') await tagsApi.add(tag, selectedItem.path);
      else await tagsApi.remove(tag, selectedItem.path);
      setTagsRefreshKey(value => value + 1);
      lastManualRefreshRef.current = Date.now();
      refresh();
      refreshSelected();
      if (activeTag) runTagSearch(activeTag, { clearResults: false, resetFilterOnFailure: false, notifyOnFailure: false });
      showToast(action === 'add' ? t('info.tag_added') : t('info.tag_removed'), 'success');
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('info.tag_update_failed'), 'error');
      return false;
    } finally {
      setTagMutationPending(false);
    }
  }, [activeTag, refresh, refreshSelected, runTagSearch, selectedItem, showToast, t, tagMutationPending, tagsApi]);

  useInvalidation(['files', 'metadata', 'tags', 'project_detail'], event => {
    // The tag mutation above already refreshed everything; the backend then
    // broadcasts the change over the WebSocket, which would trigger a second
    // identical refresh. Skip events inside the manual-refresh window (the
    // 1.5s window only risks swallowing a genuine change from another client
    // that lands within it — the next event still refreshes).
    if (Date.now() - lastManualRefreshRef.current < 1500) return;
    refresh();
    if (activeTag && (!event || event.domains.includes('tags'))) {
      runTagSearch(activeTag, { clearResults: false, resetFilterOnFailure: false, notifyOnFailure: false });
    }
    if (!event || (selectedItem && event.paths.some(path => path === selectedItem.path || selectedItem.path.startsWith(`${path}/`) || path.startsWith(`${selectedItem.path}/`)))) {
      refreshSelected();
    }
  });

  const handleInspect = useCallback((item: BrowsableItem) => {
    if (isMobile) handleNavigateDetail(item.path);
    else handleCardClick(item);
  }, [handleCardClick, handleNavigateDetail, isMobile]);

  const handleItemOpen = useCallback((item: BrowsableItem) => {
    if (item.type === 'dir' && !item.is_project) {
      handleNavigate(item.path);
      return;
    }
    handleNavigateDetail(item.path);
  }, [handleNavigate, handleNavigateDetail]);

  const handleNavigateItem = useCallback((path: string) => {
    const item = (tagResults ?? data?.items ?? []).find(candidate => candidate.path === path);
    if (item?.is_project) handleNavigateDetail(path);
    else handleNavigate(path);
  }, [data?.items, handleNavigate, handleNavigateDetail, tagResults]);

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
    void (async () => {
      if (!await guardDownload()) return;
      try {
        const { blob, filename } = await filesApi.download(path);
        triggerBlobDownload(blob, filename || path.split('/').pop() || 'download');
      } catch (err) {
        showToast(
          err instanceof Error && err.message ? err.message : t('browse.download_failed'),
          'error',
        );
      }
      void refreshQuota();
    })();
  }, [filesApi, guardDownload, refreshQuota, showToast, t]);

  const handleInfoDownload = useCallback((item: BrowsableItem) => {
    handleDownload(item.path);
  }, [handleDownload]);

  const handleInfoShare = useCallback((item: BrowsableItem) => {
    setShareDialogTrigger(document.activeElement instanceof HTMLElement ? document.activeElement : undefined);
    setSharePaths([item.path]);
  }, []);

  const visibleItems = tagResults ?? data?.items ?? [];

  const handleCopyPath = useCallback((path: string) => {
    navigator.clipboard.writeText(path).catch(() => {});
  }, []);

  const handleCopyLink = useCallback((path: string) => {
    const href = new URL(api.buildUrl(`download/${encodeURIComponent(path)}`), window.location.origin).toString();
    navigator.clipboard.writeText(href)
      .then(() => showToast(t('browse.link_copied'), 'success'))
      .catch(() => showToast(t('browse.link_copy_failed'), 'error'));
  }, [api, showToast, t]);

  const handleTagFilter = useCallback((tag: string) => {
    setActiveTag(tag);
    setSelected(new Set());
    setSearchParams({ tag }, { replace: true });
    runTagSearch(tag, { clearResults: true, resetFilterOnFailure: true, notifyOnFailure: true });
  }, [runTagSearch, setSearchParams]);

  const handleClearTagFilter = useCallback(() => {
    setActiveTag(null);
    setSearchParams(currentPath ? { path: currentPath } : {}, { replace: true });
  }, [currentPath, setSearchParams]);

  const handleDownloadSelected = useCallback(async () => {
    const paths = Array.from(selected);
    if (paths.length === 0 || downloadInFlight.current) return;
    if (!await guardDownload()) return;
    downloadInFlight.current = true;
    setIsDownloadInFlight(true);
    downloadProgress.start();
    try {
      const blob = await filesApi.batchDownload(paths, downloadProgress.update);
      triggerBlobDownload(blob, 'assets.zip');
    }
    catch (err) { showToast(err instanceof Error ? err.message : 'Failed to download ZIP archive', 'error'); }
    finally {
      downloadProgress.finish();
      downloadInFlight.current = false;
      setIsDownloadInFlight(false);
      void refreshQuota();
    }
  }, [downloadProgress, filesApi, guardDownload, refreshQuota, selected, showToast]);

  const handleSidebarToggle = useCallback(() => {
    if (isMobile) {
      setInfoOpen(false);
      try { localStorage.setItem('am_info_open', '0'); } catch {}
    }
    setSidebarOpen(prev => {
      const next = !prev;
      if (!isMobile) desktopPanelsRef.current.sidebar = next;
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
      if (!isMobile) desktopPanelsRef.current.info = next;
      try { localStorage.setItem('am_info_open', next ? '1' : '0'); } catch {}
      return next;
    });
  }, [infoOpen, isMobile]);

  const isEditableTarget = (target: EventTarget | null) => {
    if (!(target instanceof HTMLElement)) return false;
    return target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || target.isContentEditable
      || target.getAttribute('contenteditable') !== null
      || target.closest('[contenteditable]') !== null;
  };

  // ── Thumbnails ──
  const visibleLoading = activeTag ? tagLoading : isLoading;
  const imagePaths = useMemo(() => visibleItems
    .filter(item => item.category === 'image' || /\.(jpg|jpeg|png|gif|webp)$/i.test(item.extension))
    .map(item => item.path), [visibleItems]);
  useEffect(() => {
    void loadThumbnails(imagePaths);
  }, [imagePaths, loadThumbnails]);
  const thumbnailMap = useMemo(() => {
    const thumbnails: Record<string, string> = {};
    imagePaths.forEach(path => {
      const thumbnail = getThumbnail(path);
      if (thumbnail) thumbnails[path] = `data:image/jpeg;base64,${thumbnail}`;
    });
    visibleItems.forEach(item => {
      if (item.type === 'dir' && item.thumbnail_url) thumbnails[item.path] = item.thumbnail_url;
    });
    return thumbnails;
  }, [getThumbnail, imagePaths, thumbnailRevision, visibleItems]);

  useEffect(() => {
    const handleWorkspaceShortcut = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;

      // WCAG 2.1.4: single-key shortcuts (g/s) only apply while the
      // workspace — the file list component — has focus. Escape stays
      // global because it is not a single-character shortcut.
      if (event.key === 'g' || event.key === 's') {
        const workspace = workspaceRef.current;
        if (!workspace || !document.activeElement || !workspace.contains(document.activeElement)) return;
      }

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
        } else if (selectMode) {
          event.preventDefault();
          setSelectMode(false);
        } else if (isMobile && (sidebarOpen || infoOpen)) {
          event.preventDefault();
          if (infoOpen) handleInfoToggle();
          else handleSidebarToggle();
        }
      }
    };

    document.addEventListener('keydown', handleWorkspaceShortcut);
    return () => document.removeEventListener('keydown', handleWorkspaceShortcut);
  }, [activeTag, handleClearTagFilter, handleInfoToggle, handleSidebarToggle, handleViewModeChange, infoOpen, isMobile, selectMode, selected.size, sidebarOpen, viewMode]);

  return (
    <AppLayout
      header={
        onOpenPalette ? (
          <AppHeader
            activeArea="workspace"
            workspaceHref={currentPath ? '/browse?path=' + encodeURIComponent(currentPath) : '/browse'}
            galleryHref={currentPath ? '/gallery/collection?path=' + encodeURIComponent(currentPath) : '/gallery'}
            onOpenPalette={onOpenPalette}
          />
         ) : <Header />
      }
      sidebar={<Sidebar
        onNavigate={handleNavigate}
        currentPath={currentPath}
        activeTag={activeTag}
        onTagFilter={handleTagFilter}
        onClearTagFilter={handleClearTagFilter}
        tagsRefreshKey={tagsRefreshKey}
      />}
        infoPanel={<InfoPanel metadata={selectedMetadata} projectDetail={selectedProjectDetail} selected={selectedItem} loading={metadataLoading} onTagFilter={handleTagFilter} onTagAdd={canEditMetadata ? tag => mutateSelectedTag(tag, 'add') : undefined} onTagRemove={canEditMetadata ? tag => mutateSelectedTag(tag, 'remove') : undefined} tagMutationPending={tagMutationPending} onDownload={handleInfoDownload} onShare={handleInfoShare} onNotesSave={canEditMetadata ? handleNotesSave : undefined} canShare={capabilities?.manage_links ?? false} onClose={handleInfoToggle} />}
      sidebarOpen={sidebarOpen}
      infoOpen={infoOpen}
      sidebarWidth={sidebarWidth}
      infoWidth={infoWidth}
      onSidebarDragStart={handleSidebarDragStart}
      onInfoDragStart={handleInfoDragStart}
      onSidebarToggle={handleSidebarToggle}
      onInfoToggle={handleInfoToggle}
      onViewModeToggle={() => handleViewModeChange(viewMode === 'grid' ? 'list' : 'grid')}
      viewMode={viewMode === 'masonry' ? 'grid' : viewMode}
      selectMode={selectMode}
      onSelectModeToggle={() => {
        setSelectMode(prev => !prev);
        setSelected(new Set());
      }}
    >
      <div data-testid="browse-workspace" ref={workspaceRef} className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden">
       <h1 className="sr-only">{t('browse.workspace')}</h1>
       <div data-testid="file-list-header" className="flex-shrink-0">
        <Breadcrumb
         path={currentPath}
         onNavigate={handleNavigate}
         onSidebarToggle={!isMobile ? handleSidebarToggle : undefined}
         onInfoToggle={!isMobile ? handleInfoToggle : undefined}
         sidebarOpen={sidebarOpen}
         infoOpen={infoOpen}
        />

       {activeTag && (
         <div className="mx-4 mt-3 flex items-center justify-between border-b border-indigo-500/20 bg-indigo-500/5 px-3 py-2 text-xs text-indigo-200">
           <span>{t('browse.tag_banner', activeTag)}</span>
           <button type="button" onClick={handleClearTagFilter} className="rounded p-1 text-indigo-200 hover:bg-indigo-500/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400" aria-label="Clear tag filter" title="Clear tag filter">
             <X size={14} />
           </button>
         </div>
       )}

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
        selectMode={selectMode}
        onSelectModeToggle={() => {
          setSelectMode(prev => !prev);
          setSelected(new Set());
        }}
      />
       </div>

      <div data-testid="file-list-canvas" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
       {visibleLoading ? (
        <div data-testid="file-list-loading-grid" role="status" aria-label={t('browse.loading')} className="grid w-full min-w-0 grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3 p-4">
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
          <button
            type="button"
            onClick={() => void refresh()}
            className="mt-4 px-4 py-2 text-sm text-white bg-brand-500 hover:bg-brand-600 rounded-lg transition-colors"
          >
            {t('gallery.retry')}
          </button>
        </div>
      ) : visibleItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
          <p className="text-base">{t('browse.empty')}</p>
        </div>
      ) : viewMode === 'masonry' ? (
        <MasonryView
          items={visibleItems}
          selected={selected}
          selectionMode={selectMode}
          onSelect={handleSelect}
          onInspect={handleInspect}
          onNavigate={handleNavigateItem}
          getThumbnail={path => thumbnailMap[path]}
          onContextMenu={handleContextMenu}
          onTagClick={handleTagFilter}
          onDoubleClick={handleItemOpen}
          onDownload={item => handleDownload(item.path)}
          isMobile={isMobile}
        />
      ) : viewMode === 'grid' ? (
        <ProjectGrid
          items={visibleItems}
          selected={selected}
          onSelect={handleSelect}
          onZipSelect={handleSelect}
          onInspect={handleInspect}
          onNavigate={handleNavigateItem}
          selectionMode={selectMode}
          onDoubleClick={handleItemOpen}
          isMobile={isMobile}
          onContextMenu={handleContextMenu}
          thumbnailMap={thumbnailMap}
           onDirectoryVisible={handleDirectoryVisible}
           onTagClick={handleTagFilter}
           onCopyLink={handleCopyLink}
           onDownload={item => handleDownload(item.path)}
        />
      ) : (
        <ProjectList
          items={visibleItems}
          selected={selected}
          onSelect={handleSelect}
          onZipSelect={handleSelect}
          onInspect={handleInspect}
          onNavigate={handleNavigateItem}
          selectionMode={selectMode}
          onDoubleClick={handleItemOpen}
          isMobile={isMobile}
           onContextMenu={handleContextMenu}
           onDirectoryVisible={handleDirectoryVisible}
           onCopyLink={handleCopyLink}
           onTagClick={handleTagFilter}
           onDownload={item => handleDownload(item.path)}
           thumbnailMap={thumbnailMap}
        />
      )}
      </div>

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
             { label: t('action.copy_download_link'), icon: <Link2 size={13} />, onClick: () => handleCopyLink(contextMenu.item.path) },
            { label: t('action.copy_path'), icon: <Copy size={13} />, onClick: () => handleCopyPath(contextMenu.item.path) },
          ]}
        />
      )}
      </div>

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
