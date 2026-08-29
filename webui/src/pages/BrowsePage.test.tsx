// @vitest-environment jsdom
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BrowsePage from './BrowsePage';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { DownloadProgressProvider } from '../components/ui/DownloadProgress';
import { useMediaQuery } from '../hooks/useMediaQuery';
import type { BrowsableItem } from '../types/api';

const search = vi.fn();
const getMeta = vi.fn();
const getProjectDetail = vi.fn();
const batchDownload = vi.fn();
const addTag = vi.fn();
const removeTag = vi.fn();
const projectsRefresh = vi.fn();
const showToast = vi.fn();
const getThumbnail = vi.fn();
const loadThumbnails = vi.fn();
const { useInvalidationMock } = vi.hoisted(() => ({ useInvalidationMock: vi.fn() }));
let listingItems: BrowsableItem[] = [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }];
const buildUrl = vi.fn((path: string) => `/library/api/${path}`);
const authState = { api: { buildUrl }, identityGeneration: 0, capabilities: { settings: true } };

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => authState,
}));

vi.mock('../hooks/useProjects', () => ({
  useProjects: (initialPath: string) => {
    const [currentPath, navigateTo] = useState(initialPath);
    return {
      data: { items: listingItems.map(item => currentPath ? { ...item, name: `listing:${currentPath}` } : item) },
      isLoading: false,
      error: null,
      currentPath,
      sort: { sort: 'name', order: 'asc' },
      navigateTo,
      setSort: vi.fn(),
      refresh: projectsRefresh,
      listingGeneration: 0,
      hydrateDirectories: vi.fn(),
    };
  },
}));

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }));
vi.mock('../hooks/useInvalidation', () => ({
  useInvalidation: useInvalidationMock,
}));
vi.mock('../hooks/useThumbnailCache', () => ({
  useThumbnailCache: () => ({ loadThumbnails, getThumbnail, revision: 0 }),
}));
vi.mock('../hooks/useMediaQuery', () => ({ useMediaQuery: vi.fn(() => false) }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('../hooks/useQuota', () => ({
  useQuota: () => ({ guardDownload: async () => true, refresh: vi.fn(), quota: null }),
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../api/files', () => ({ createFilesApi: () => ({ download: vi.fn(), batchDownload }) }));
vi.mock('../api/tags', () => ({ createTagsApi: () => ({ add: addTag, remove: removeTag, list: vi.fn(), rename: vi.fn(), delete: vi.fn() }) }));
vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ getMeta, getProjectDetail, search }),
}));
vi.mock('../components/layout/AppLayout', () => ({ AppLayout: ({ children, infoPanel, onSelectModeToggle, selectMode, viewMode }: { children: React.ReactNode; infoPanel: React.ReactNode; onSelectModeToggle?: () => void; selectMode?: boolean; viewMode?: string }) => <>{infoPanel}<output data-testid="view-mode">{viewMode}</output><button aria-label={selectMode ? 'mobile.done' : 'mobile.select'} onClick={onSelectModeToggle}>Toggle selection</button>{children}</> }));
vi.mock('../components/layout/Header', () => ({ Header: () => null }));
vi.mock('../components/layout/Sidebar', () => ({ Sidebar: () => null }));
vi.mock('../components/layout/InfoPanel', () => ({
  InfoPanel: ({ onTagFilter, metadata, projectDetail, selected, loading }: { onTagFilter?: (tag: string) => void; metadata?: { path?: string } | null; projectDetail?: { thumbnail_url?: string | null } | null; selected?: { path?: string; size?: number; size_fmt?: string; modified?: number } | null; loading?: boolean }) => (
    <>
      <output data-testid="metadata">{loading ? 'loading' : metadata?.path ?? 'none'}</output>
      <output data-testid="project-preview">{projectDetail?.thumbnail_url ?? 'none'}</output>
      <output data-testid="inspected-item">{selected?.path ?? 'none'}</output>
      <output data-testid="inspected-technical-fields">{JSON.stringify({ size: selected?.size, size_fmt: selected?.size_fmt, modified: selected?.modified })}</output>
      <button onClick={() => onTagFilter?.('featured')}>Filter tag</button>
      <button onClick={() => onTagFilter?.('first')}>Filter first tag</button>
      <button onClick={() => onTagFilter?.('second')}>Filter second tag</button>
    </>
  ),
}));
vi.mock('../components/files/Breadcrumb', () => ({ Breadcrumb: () => null }));
vi.mock('../components/files/FileToolbar', () => ({ FileToolbar: ({ selectedCount, activeTag, onClearTag, onDownloadSelected, isDownloadInFlight, onTagSelected }: { selectedCount: number; activeTag?: string | null; onClearTag?: () => void; onDownloadSelected: () => void; isDownloadInFlight?: boolean; onTagSelected?: () => void }) => <div data-testid="file-toolbar"><output data-testid="selected-count">{selectedCount}</output>{activeTag && <><output data-testid="active-tag">{activeTag}</output><button onClick={onClearTag}>Clear tag filter</button></>}{onTagSelected && <button onClick={onTagSelected} disabled={selectedCount === 0}>Tag selected</button>}{selectedCount > 0 && <button onClick={onDownloadSelected} disabled={isDownloadInFlight}>{isDownloadInFlight ? 'Downloading selected' : 'Download selected'}</button>}</div> }));
vi.mock('../components/files/ProjectGrid', () => ({ ProjectGrid: (props: { items: Array<{ name: string; path: string; type: string; is_project?: boolean; size?: number; size_fmt?: string; modified?: number }>; onSelect: (path: string) => void; onInspect: (item: { path: string; size?: number; size_fmt?: string; modified?: number }) => void; onNavigate?: (path: string) => void; onZipSelect?: (path: string) => void; onDoubleClick: (item: { path: string; type: string; is_project?: boolean }) => void; onContextMenu?: (event: React.MouseEvent, item: { path: string; type: string }) => void; selectionMode?: boolean; thumbnailMap: Record<string, string>; isMobile?: boolean }) => <><output data-testid="file-list">{props.items.map(item => item.name).join(',')}</output><output data-testid="file-list-technical-fields">{JSON.stringify(props.items.map(({ size, size_fmt, modified }) => ({ size, size_fmt, modified })))}</output><output data-testid="thumbnail-map">{JSON.stringify(props.thumbnailMap)}</output><button onClick={() => props.selectionMode ? props.onSelect(props.items[0]!.path) : props.onInspect(props.items[0]!)}>Select asset</button>{props.items[1] && <button onClick={() => props.selectionMode ? props.onSelect(props.items[1]!.path) : props.onInspect(props.items[1]!)}>Select second asset</button>}<button onClick={() => props.onZipSelect?.('asset.png')}>Select asset for ZIP</button><button onClick={() => props.onInspect(props.items[0]!)}>Inspect asset</button><button onClick={() => props.onDoubleClick(props.items[0]!)}>Open asset</button><button onClick={() => props.isMobile && props.items[0]?.type === 'dir' ? props.onNavigate?.(props.items[0].path) : props.onInspect(props.items[0]!)}>Click directory</button><button onClick={() => props.isMobile && props.items[0]?.type === 'dir' ? props.onNavigate?.(props.items[0].path) : props.onDoubleClick(props.items[0]!)}>Double click directory</button><button onContextMenu={event => props.onContextMenu?.(event, props.items[0]!)}>Open item context menu</button></> }));
vi.mock('../components/files/ProjectList', () => ({ ProjectList: (props: { items: Array<{ path: string; type?: string }>; onSelect: (path: string) => void; onInspect: (item: { path: string }) => void; onNavigate?: (path: string) => void; onDoubleClick?: (item: { path: string }) => void; selectionMode?: boolean; thumbnailMap?: Record<string, string>; isMobile?: boolean }) => <><output data-testid="thumbnail-map">{JSON.stringify(props.thumbnailMap)}</output><button onClick={() => props.selectionMode ? props.onSelect(props.items[0]!.path) : props.onInspect(props.items[0]!)}>List asset</button><button onClick={() => props.isMobile && props.items[0]?.type === 'dir' ? props.onNavigate?.(props.items[0].path) : props.onInspect(props.items[0]!)}>Click directory</button><button onClick={() => props.isMobile && props.items[0]?.type === 'dir' ? props.onNavigate?.(props.items[0].path) : props.onDoubleClick?.(props.items[0]!)}>Double click directory</button></> }));
vi.mock('../components/ui/Skeleton', () => ({ Skeleton: () => null }));
vi.mock('../components/shares/ShareDialog', () => ({ ShareDialog: () => null }));

function LocationSearch() {
  return <output data-testid="location-search">{useLocation().search}</output>;
}

function LocationPath() {
  return <output data-testid="location-path">{useLocation().pathname}</output>;
}

function NavigateToNewPath() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/browse?path=newer%2Furl')}>Navigate URL</button>;
}

function TestBrowsePage() {
  return (
    <QueryCacheProvider>
      <DownloadProgressProvider><BrowsePage /></DownloadProgressProvider>
    </QueryCacheProvider>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('BrowsePage', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.removeItem('am_view');
  });

  beforeEach(() => {
    localStorage.removeItem('am_view');
    listingItems = [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }];
    vi.mocked(useMediaQuery).mockReturnValue(false);
    localStorage.clear();
    buildUrl.mockClear();
    search.mockReset();
    search.mockResolvedValue({ results: [{ path: 'tagged/item', name: 'item', type: 'file', extension: '', category: 'other' }] });
    getMeta.mockReset();
    getMeta.mockResolvedValue({ path: 'asset.png' });
    getProjectDetail.mockReset();
    getProjectDetail.mockResolvedValue({
      path: 'folder',
      thumbnail_url: '/api/thumbnails/folder/cover.png',
      images: [],
      tags: [],
      notes: '',
      urls: [],
    });
    batchDownload.mockReset();
    batchDownload.mockResolvedValue(undefined);
    addTag.mockReset();
    addTag.mockResolvedValue({ ok: true });
    removeTag.mockReset();
    removeTag.mockResolvedValue({ ok: true });
    projectsRefresh.mockReset();
    showToast.mockReset();
    getThumbnail.mockReset();
    loadThumbnails.mockReset();
    useInvalidationMock.mockReset();
    authState.identityGeneration = 0;
  });

  it('registers the Browse projection domains', () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    const pageDomains = ['files', 'metadata', 'tags', 'project_detail'];
    expect(useInvalidationMock.mock.calls.some(
      ([domains]) => JSON.stringify(domains) === JSON.stringify(pageDomains),
    )).toBe(true);
  });

  it('clears an inspected projection before a previous identity response resolves', async () => {
    const stale = deferred<{ path: string }>();
    getMeta.mockReturnValueOnce(stale.promise);
    const { rerender } = render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Inspect asset' }));
    await waitFor(() => expect(screen.getByTestId('inspected-item').textContent).toBe('asset.png'));

    authState.identityGeneration = 1;
    rerender(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId('inspected-item').textContent).toBe('none'));

    stale.resolve({ path: 'asset.png' });
    await Promise.resolve();
    expect(screen.getByTestId('metadata').textContent).toBe('none');
  });

  it('omits Detail from directory context menus while retaining it for files', () => {
    listingItems = [{ path: 'nested', name: 'nested', type: 'dir', extension: '', category: 'other', size_fmt: '', modified: 0 }];
    const { unmount } = render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.contextMenu(screen.getByRole('button', { name: 'Open item context menu' }));
    expect(screen.queryByRole('menuitem', { name: 'action.detail' })).toBeNull();

    unmount();
    listingItems = [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.contextMenu(screen.getByRole('button', { name: 'Open item context menu' }));
    expect(screen.getByRole('menuitem', { name: 'action.detail' })).toBeDefined();
  });

  it('copies an absolute download URL while honoring the configured API base path', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.contextMenu(screen.getByRole('button', { name: 'Open item context menu' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'action.copy_download_link' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      'http://localhost:3000/library/api/download/asset.png',
    ));
    expect(buildUrl).toHaveBeenCalledWith('download/asset.png');
  });
  it('shows the selected tag and clears back to the current directory listing', async () => {
    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <TestBrowsePage />
        <LocationSearch />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(screen.getByTestId('active-tag').textContent).toBe('featured'));
    expect(search).toHaveBeenCalledWith('', 'featured', undefined, expect.any(AbortSignal));
    expect(screen.getByTestId('location-search').textContent).toBe('?tag=featured');
    fireEvent.click(screen.getByTitle('browse.clear_tag'));
    expect(screen.queryByTestId('active-tag')).toBeNull();
  });

  it('does not fabricate technical fields for tag search results', async () => {
    search.mockResolvedValueOnce({ results: [{ path: 'tagged/item', name: 'item', type: 'file', extension: '.png', category: 'image' }] });
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('item'));
    expect(screen.getByTestId('file-list-technical-fields').textContent).toBe('[{}]');
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    expect(screen.getByTestId('inspected-technical-fields').textContent).toBe('{}');
  });

  it('flags a partial tag search and reports the dropped match count', async () => {
    search.mockResolvedValueOnce({
      results: [{ path: 'tagged/item', name: 'item', type: 'file', extension: '', category: 'other' }],
      status: 'partial',
      dropped_count: 12,
    });
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('item'));
    expect(screen.getByTestId('tag-search-notice').textContent).toBe('browse.search_partial_dropped');
  });

  it('flags a degraded tag search that fell back to name matching', async () => {
    search.mockResolvedValueOnce({
      results: [{ path: 'tagged/item', name: 'item', type: 'file', extension: '', category: 'other' }],
      status: 'degraded',
    });
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('item'));
    expect(screen.getByTestId('tag-search-notice').textContent).toBe('browse.search_degraded');
  });

  it('shows no truncation notice for an unmarked tag search', async () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('item'));
    expect(screen.queryByTestId('tag-search-notice')).toBeNull();
  });

  it('downloads exactly the selected items', async () => {
    const { useMediaQuery } = await import('../hooks/useMediaQuery');
    vi.mocked(useMediaQuery).mockReturnValue(true);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: 'Download selected' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download selected' }));
    await waitFor(() => expect(batchDownload).toHaveBeenCalledWith(['asset.png'], expect.any(Function)));
  });

  it('closes and persists both workspace panels when the viewport becomes mobile', async () => {
    vi.mocked(useMediaQuery).mockReturnValue(false);
    const view = render(<MemoryRouter><TestBrowsePage /></MemoryRouter>);
    localStorage.setItem('am_sidebar_open', '1');
    localStorage.setItem('am_info_open', '1');

    vi.mocked(useMediaQuery).mockReturnValue(true);
    view.rerender(<MemoryRouter><TestBrowsePage /></MemoryRouter>);

    await waitFor(() => {
      expect(localStorage.getItem('am_sidebar_open')).toBe('0');
      expect(localStorage.getItem('am_info_open')).toBe('0');
    });
  });

  it('keeps the FileList controls outside the scrolling asset canvas', () => {
    render(<MemoryRouter><TestBrowsePage /></MemoryRouter>);

    const workspace = screen.getByTestId('browse-workspace');
    const header = screen.getByTestId('file-list-header');
    const canvas = screen.getByTestId('file-list-canvas');
    const toolbar = screen.getByTestId('file-toolbar');

    expect(workspace.className).toContain('overflow-hidden');
    expect(header.className).toContain('flex-shrink-0');
    expect(canvas.className).toContain('flex-1');
    expect(canvas.className).toContain('min-h-0');
    expect(canvas.className).toContain('overflow-y-auto');
    expect(header.contains(toolbar)).toBe(true);
    expect(canvas.contains(toolbar)).toBe(false);
  });

  it('restores the desktop panel state when the viewport leaves mobile', async () => {
    localStorage.setItem('am_sidebar_open', '1');
    localStorage.setItem('am_info_open', '1');
    vi.mocked(useMediaQuery).mockReturnValue(false);
    const view = render(<MemoryRouter><TestBrowsePage /></MemoryRouter>);

    vi.mocked(useMediaQuery).mockReturnValue(true);
    view.rerender(<MemoryRouter><TestBrowsePage /></MemoryRouter>);
    await waitFor(() => expect(localStorage.getItem('am_sidebar_open')).toBe('0'));

    vi.mocked(useMediaQuery).mockReturnValue(false);
    view.rerender(<MemoryRouter><TestBrowsePage /></MemoryRouter>);

    await waitFor(() => {
      expect(localStorage.getItem('am_sidebar_open')).toBe('1');
      expect(localStorage.getItem('am_info_open')).toBe('1');
    });
  });

  it('reports a selected ZIP download failure and clears progress', async () => {
    const pending = deferred<void>();
    batchDownload.mockReturnValueOnce(pending.promise);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download selected' }));

    await waitFor(() => expect(screen.getByRole('progressbar', { name: 'action.download_in_progress' })).toBeDefined());
    pending.reject(new Error('ZIP failed'));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith('ZIP failed', 'error'));
    expect(screen.queryByRole('progressbar', { name: 'action.download_in_progress' })).toBeNull();
  });

  it('clears a failed tag filter and restores the directory listing', async () => {
    search.mockRejectedValueOnce(new Error('Tag search failed'));
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    expect(screen.getByTestId('file-list').textContent).toBe('asset.png');
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('info.tag_filter_failed', 'error'));
    // Toast + tag-clear + listing-restore are separate state updates; under
    // CI load they land in distinct act flushes, so assert each by waiting.
    await waitFor(() => expect(screen.queryByTestId('active-tag')).toBeNull());
    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('asset.png'));
  });

  it('only selects an asset after mobile selection mode is enabled', async () => {
    const { useMediaQuery } = await import('../hooks/useMediaQuery');
    vi.mocked(useMediaQuery).mockReturnValue(true);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'mobile.select' })).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    expect(screen.getByTestId('selected-count').textContent).toBe('0');
    getMeta.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    expect(screen.getByTestId('selected-count').textContent).toBe('1');
    expect(getMeta).not.toHaveBeenCalled();
  });

  it('does not request metadata in grid or list selection mode', async () => {
    const { useMediaQuery } = await import('../hooks/useMediaQuery');
    vi.mocked(useMediaQuery).mockReturnValue(true);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    expect(getMeta).not.toHaveBeenCalled();
    cleanup();
    localStorage.setItem('am_view', 'list');
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'List asset' }));
    expect(getMeta).not.toHaveBeenCalled();
    localStorage.removeItem('am_view');
  });

  it('ignores stale metadata responses and cleanup from an older card', async () => {
    const first = deferred<{ path: string }>();
    const second = deferred<{ path: string }>();
    getMeta.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    second.resolve({ path: 'newer' });
    await waitFor(() => expect(screen.getByTestId('metadata').textContent).toBe('newer'));
    first.resolve({ path: 'older' });
    await waitFor(() => expect(getMeta).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('metadata').textContent).toBe('newer');
  });

  it('ignores stale metadata failure and finally while the newer card is loading', async () => {
    const first = deferred<{ path: string }>();
    const second = deferred<{ path: string }>();
    getMeta.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    first.reject(new Error('stale failure'));
    await waitFor(() => expect(getMeta).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('metadata').textContent).toBe('loading');
    second.resolve({ path: 'newer' });
    await waitFor(() => expect(screen.getByTestId('metadata').textContent).toBe('newer'));
  });

  it('aborts and invalidates an active metadata request on unmount', () => {
    const pending = deferred<{ path: string }>();
    getMeta.mockClear();
    getMeta.mockReturnValueOnce(pending.promise);
    const view = render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    const signal = getMeta.mock.calls[getMeta.mock.calls.length - 1]?.[1] as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    pending.resolve({ path: 'stale' });
  });

  it('authoritatively refetches the active tag results when tags projection invalidates', async () => {
    const initial = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    const refreshed = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    buildUrl.mockClear();
    search.mockReset();
    search.mockReturnValueOnce(initial.promise).mockReturnValueOnce(refreshed.promise);

    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));

    const invalidate = useInvalidationMock.mock.calls[useInvalidationMock.mock.calls.length - 1]?.[1] as ((event: unknown) => void) | undefined;
    invalidate?.({ type: 'projection_invalidated', domains: ['tags'], paths: [], epoch: 'epoch', revision: 1 });

    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(search).toHaveBeenNthCalledWith(2, '', 'featured', undefined, expect.any(AbortSignal));
    expect(search.mock.calls[0]?.[3].aborted).toBe(true);

    refreshed.resolve({ results: [{ path: 'refreshed/item', name: 'refreshed', type: 'file', extension: '', category: 'other' }] });
    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('refreshed'));

    initial.resolve({ results: [{ path: 'stale/item', name: 'stale', type: 'file', extension: '', category: 'other' }] });
    await act(async () => { await initial.promise; });
    expect(screen.getByTestId('file-list').textContent).toBe('refreshed');
  });

  it('authoritatively refetches the active tag results after null recovery invalidation', async () => {
    const initial = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    const refreshed = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    buildUrl.mockClear();
    search.mockReset();
    search.mockReturnValueOnce(initial.promise).mockReturnValueOnce(refreshed.promise);

    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));

    const invalidate = useInvalidationMock.mock.calls[useInvalidationMock.mock.calls.length - 1]?.[1] as ((event: unknown) => void) | undefined;
    invalidate?.(null);

    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(search).toHaveBeenNthCalledWith(2, '', 'featured', undefined, expect.any(AbortSignal));
    expect(search.mock.calls[0]?.[3].aborted).toBe(true);

    refreshed.resolve({ results: [{ path: 'recovered/item', name: 'recovered', type: 'file', extension: '', category: 'other' }] });
    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('recovered'));

    initial.resolve({ results: [{ path: 'stale/item', name: 'stale', type: 'file', extension: '', category: 'other' }] });
    await act(async () => { await initial.promise; });
    expect(screen.getByTestId('file-list').textContent).toBe('recovered');
  });

  it('does not refetch the active tag for unrelated projection invalidations', async () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));

    const invalidate = useInvalidationMock.mock.calls[useInvalidationMock.mock.calls.length - 1]?.[1] as ((event: unknown) => void) | undefined;
    for (const domain of ['files', 'metadata', 'project_detail']) {
      invalidate?.({ type: 'projection_invalidated', domains: [domain], paths: [], epoch: 'epoch', revision: 1 });
    }

    expect(search).toHaveBeenCalledTimes(1);
  });

  it('ignores an older tag search that resolves after a newer one', async () => {
    const first = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    const second = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    buildUrl.mockClear();
    search.mockReset();
    search.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <TestBrowsePage />
        <LocationSearch />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter first tag' }));
    fireEvent.click(screen.getByRole('button', { name: 'Filter second tag' }));

    second.resolve({ results: [{ path: 'newer/item', name: 'newer', type: 'file', extension: '', category: 'other' }] });
    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('newer'));

    first.resolve({ results: [{ path: 'older/item', name: 'older', type: 'file', extension: '', category: 'other' }] });
    await act(async () => { await first.promise; });
    expect(screen.getByTestId('active-tag').textContent).toBe('second');
    expect(screen.getByTestId('file-list').textContent).toBe('newer');
  });

  it('ignores a pending tag search after router search params change', async () => {
    const pending = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    buildUrl.mockClear();
    search.mockReset();
    search.mockReturnValueOnce(pending.promise);

    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <TestBrowsePage />
        <NavigateToNewPath />
        <LocationSearch />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    fireEvent.click(screen.getByRole('button', { name: 'Navigate URL' }));
    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=newer%2Furl'));

    pending.resolve({ results: [{ path: 'stale/tag-result', name: 'stale', type: 'file', extension: '', category: 'other' }] });
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('location-search').textContent).toBe('?path=newer%2Furl');
  });

  it('runs a workspace name search from the q param and shows the result count', async () => {
    search.mockResolvedValueOnce({
      results: [
        { path: 'found/one.png', name: 'one.png', type: 'file', extension: '.png', category: 'image' },
        { path: 'found/two.jpg', name: 'two.jpg', type: 'file', extension: '.jpg', category: 'image' },
      ],
      count: 2,
    });
    render(
      <MemoryRouter initialEntries={['/browse?q=hero']}>
        <TestBrowsePage />
        <LocationSearch />
      </MemoryRouter>,
    );

    await waitFor(() => expect(search).toHaveBeenCalledWith('hero', undefined, undefined, expect.any(AbortSignal)));
    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('one.png,two.jpg'));
    expect(screen.getByTestId('name-search-banner').textContent).toBe('browse.search_banner');
  });

  it('shows the dedicated empty state when a name search has no results', async () => {
    search.mockResolvedValueOnce({ results: [], count: 0 });
    render(<MemoryRouter initialEntries={['/browse?q=missing']}><TestBrowsePage /></MemoryRouter>);

    await waitFor(() => expect(search).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText('browse.search_no_results')).toBeTruthy());
    expect(screen.getByTestId('name-search-banner').textContent).toBe('browse.search_banner');
  });

  it('toasts and falls back to the listing when a name search fails', async () => {
    search.mockRejectedValueOnce(new Error('boom'));
    render(
      <MemoryRouter initialEntries={['/browse?path=original&q=hero']}>
        <TestBrowsePage />
        <LocationSearch />
      </MemoryRouter>,
    );

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('browse.search_failed', 'error'));
    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=original'));
    expect(screen.getByTestId('file-list').textContent).toBe('listing:original');
  });

  it('inspects a desktop click without adding the item to the ZIP selection', async () => {
    const { useMediaQuery } = await import('../hooks/useMediaQuery');
    vi.mocked(useMediaQuery).mockReturnValue(false);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));

    expect(screen.getByTestId('inspected-item').textContent).toBe('asset.png');
    expect(screen.getByTestId('selected-count').textContent).toBe('0');
  });

  it('keeps the browse URL and loads legacy project preview detail when a desktop directory is clicked once', async () => {
    listingItems = [{ path: 'folder', name: 'folder', type: 'dir', extension: '', category: 'other', size_fmt: '', modified: 0 }];
    getProjectDetail.mockResolvedValueOnce({
      path: 'folder',
      thumbnail_url: '/api/thumbnails/folder/cover.png',
      images: [{ name: 'cover.png', url: '/api/thumbnails/folder/cover.png?size=1920', thumb_url: '/api/thumbnails/folder/cover.png' }],
      tags: [], notes: '', urls: [],
    });
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /><LocationSearch /><LocationPath /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Click directory' }));

    await waitFor(() => expect(screen.getByTestId('inspected-item').textContent).toBe('folder'));
    expect(getProjectDetail).toHaveBeenCalledWith('folder', expect.any(AbortSignal));
    expect(getMeta).not.toHaveBeenCalled();
    expect(screen.getByTestId('project-preview').textContent).toBe('/api/thumbnails/folder/cover.png');
    expect(screen.getByTestId('location-search').textContent).toBe('');
  });

  it('browses into an ordinary directory on desktop double click', async () => {
    listingItems = [{ path: 'folder', name: 'folder', type: 'dir', extension: '', category: 'other', size_fmt: '', modified: 0 }];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /><LocationSearch /><LocationPath /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Double click directory' }));

    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=folder'));
    expect(screen.getByTestId('inspected-item').textContent).toBe('none');
  });

  it('opens a project directory detail on desktop double click', async () => {
    listingItems = [{ path: 'project', name: 'project', type: 'dir', is_project: true, extension: '', category: 'other', size_fmt: '', modified: 0 }];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /><LocationSearch /><LocationPath /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Double click directory' }));

    await waitFor(() => expect(screen.getByTestId('location-path').textContent).toBe('/detail'));
  });

  it('routes mobile project and ordinary directory clicks according to directory type', async () => {
    vi.mocked(useMediaQuery).mockReturnValue(true);
    listingItems = [{ path: 'project', name: 'project', type: 'dir', is_project: true, extension: '', category: 'other', size_fmt: '', modified: 0 }];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /><LocationSearch /><LocationPath /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Click directory' }));
    await waitFor(() => expect(screen.getByTestId('location-path').textContent).toBe('/detail'));

    cleanup();
    listingItems = [{ path: 'folder', name: 'folder', type: 'dir', extension: '', category: 'other', size_fmt: '', modified: 0 }];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /><LocationSearch /><LocationPath /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Click directory' }));
    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=folder'));
  });

  it('selects from the desktop ZIP control without opening InfoPanel, while the card still inspects', async () => {
    vi.mocked(useMediaQuery).mockReturnValue(false);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Select asset for ZIP' }));
    expect(screen.getByTestId('selected-count').textContent).toBe('1');
    expect(screen.getByTestId('inspected-item').textContent).toBe('none');
    expect(getMeta).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Inspect asset' }));
    await waitFor(() => expect(screen.getByTestId('inspected-item').textContent).toBe('asset.png'));
    expect(screen.getByTestId('selected-count').textContent).toBe('1');
  });

  it('clears a successful tag filter and renders the new directory after direct URL navigation', async () => {
    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <TestBrowsePage />
        <NavigateToNewPath />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    await waitFor(() => expect(screen.getByTestId('file-list').textContent).toBe('item'));
    fireEvent.click(screen.getByRole('button', { name: 'Navigate URL' }));

    await waitFor(() => expect(screen.queryByTestId('active-tag')).toBeNull());
    expect(screen.getByTestId('file-list').textContent).toBe('listing:newer/url');
  });

  it('bulk-adds a tag to every selected path and refreshes the listing', async () => {
    listingItems = [
      { path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 },
      { path: 'second.png', name: 'second.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 },
    ];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    expect(screen.queryByRole('button', { name: 'Tag selected' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    expect((screen.getByRole('button', { name: 'Tag selected' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select second asset' }));
    expect((screen.getByRole('button', { name: 'Tag selected' }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Tag selected' }));
    const input = screen.getByLabelText('browse.bulk_tag_placeholder') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hero' } });
    fireEvent.click(screen.getByRole('button', { name: 'browse.bulk_tag_add' }));

    await waitFor(() => expect(addTag).toHaveBeenCalledTimes(2));
    expect(addTag).toHaveBeenCalledWith('hero', 'asset.png');
    expect(addTag).toHaveBeenCalledWith('hero', 'second.png');
    expect(removeTag).not.toHaveBeenCalled();
    await waitFor(() => expect(showToast).toHaveBeenCalledWith('browse.bulk_tag_added', 'success'));
    expect(projectsRefresh).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByTestId('bulk-tag-panel')).toBeNull());
    expect(screen.getByTestId('selected-count').textContent).toBe('0');
  });

  it('reports the partial bulk-tag failure without dropping the successful paths', async () => {
    listingItems = [
      { path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 },
      { path: 'second.png', name: 'second.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 },
    ];
    addTag.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new Error('denied'));
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select second asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tag selected' }));
    fireEvent.change(screen.getByLabelText('browse.bulk_tag_placeholder'), { target: { value: 'hero' } });
    fireEvent.click(screen.getByRole('button', { name: 'browse.bulk_tag_add' }));

    await waitFor(() => expect(addTag).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith('browse.bulk_tag_partial', 'error'));
    expect(projectsRefresh).toHaveBeenCalled();
    expect(screen.getByTestId('selected-count').textContent).toBe('2');
  });

  it('serializes selected ZIP downloads until the active transfer finishes', async () => {
    const pending = deferred<void>();
    batchDownload.mockReturnValueOnce(pending.promise);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    const downloadButton = screen.getByRole('button', { name: 'Download selected' });
    fireEvent.click(downloadButton);

    await waitFor(() => expect(batchDownload).toHaveBeenCalledTimes(1));
    expect((screen.getByRole('button', { name: 'Downloading selected' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Downloading selected' }));
    expect(batchDownload).toHaveBeenCalledTimes(1);

    pending.resolve();
    await waitFor(() => expect((screen.getByRole('button', { name: 'Download selected' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByRole('progressbar', { name: 'action.download_in_progress' })).toBeNull();
  });

  it('applies workspace shortcuts outside editable elements and clears transient state before selection', async () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    // Single-key shortcuts apply while the workspace has focus (WCAG 2.1.4).
    screen.getByRole('button', { name: 'Select asset' }).focus();
    fireEvent.keyDown(document, { key: 'g' });
    expect(screen.getByTestId('view-mode').textContent).toBe('list');
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    await waitFor(() => expect(screen.getByTestId('active-tag').textContent).toBe('featured'));
    // The view switch unmounted the focused grid button; keep focus inside
    // the workspace so the single-key shortcut still applies.
    screen.getByRole('button', { name: 'List asset' }).focus();
    fireEvent.keyDown(document, { key: 's' });
    expect(screen.getByRole('button', { name: 'mobile.done' })).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'List asset' }));
    expect(screen.getByTestId('selected-count').textContent).toBe('1');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('active-tag')).toBeNull();
    expect(screen.getByTestId('selected-count').textContent).toBe('1');
    fireEvent.keyDown(document, { key: 'Escape', shiftKey: true });
    expect(screen.getByTestId('selected-count').textContent).toBe('1');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByTestId('selected-count').textContent).toBe('0');

    const input = document.createElement('input');
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: 's' });
    expect(screen.getByRole('button', { name: 'mobile.done' })).toBeDefined();
    input.remove();
  });

  it('ignores single-key workspace shortcuts while focus is outside the workspace', () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    // Focus stays on the body: g/s must not fire (WCAG 2.1.4 scoping).
    fireEvent.keyDown(document, { key: 'g' });
    expect(screen.getByTestId('view-mode').textContent).toBe('grid');
    fireEvent.keyDown(document, { key: 's' });
    expect(screen.getByRole('button', { name: 'mobile.select' })).toBeDefined();
  });

  it('passes file and directory thumbnails to the project view', () => {
    listingItems = [
      { path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 },
      { path: 'folder', name: 'folder', type: 'dir', extension: '', category: 'other', thumbnail_url: '/api/thumbnails/folder.jpg', size_fmt: '', modified: 0 },
    ];
    getThumbnail.mockReturnValue('ZmFrZQ==');
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    expect(screen.getByTestId('thumbnail-map').textContent).toBe(JSON.stringify({
      'asset.png': 'data:image/jpeg;base64,ZmFrZQ==',
      folder: '/api/thumbnails/folder.jpg',
    }));

    cleanup();
    localStorage.setItem('am_view', 'list');
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    expect(screen.getByTestId('thumbnail-map').textContent).toBe(JSON.stringify({
      'asset.png': 'data:image/jpeg;base64,ZmFrZQ==',
      folder: '/api/thumbnails/folder.jpg',
    }));
  });

  it('loads file thumbnails in list view', async () => {
    localStorage.setItem('am_view', 'list');
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    await waitFor(() => expect(loadThumbnails).toHaveBeenCalledWith(['asset.png']));
  });

  it('exposes the workspace search as a searchbox and does not intercept editable fields', async () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    const search = document.createElement('input');
    search.id = 'header-search-input';
    search.setAttribute('role', 'searchbox');
    document.body.append(search);
    search.focus();
    fireEvent.keyDown(search, { key: 'g' });
    fireEvent.keyDown(search, { key: 's' });
    expect(screen.getByRole('button', { name: 'mobile.select' })).toBeDefined();
    expect(document.activeElement).toBe(search);
    search.remove();
  });

  it('focuses the workspace search with slash only outside editable elements', () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    const search = document.createElement('input');
    search.id = 'header-search-input';
    search.setAttribute('role', 'searchbox');
    document.body.append(search);
    const editor = document.createElement('div');
    editor.setAttribute('contenteditable', 'true');
    document.body.append(editor);
    editor.focus();
    fireEvent.keyDown(editor, { key: '/' });
    expect(document.activeElement).toBe(editor);
    editor.remove();
    search.remove();
  });
});
