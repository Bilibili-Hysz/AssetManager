// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BrowsePage from './BrowsePage';
import { DownloadProgressProvider } from '../components/ui/DownloadProgress';
import { useMediaQuery } from '../hooks/useMediaQuery';

const search = vi.fn();
const getMeta = vi.fn();
const batchDownload = vi.fn();
const showToast = vi.fn();
let listingItems = [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }];

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ api: {}, user: null }),
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
      refresh: vi.fn(),
      listingGeneration: 0,
      hydrateDirectories: vi.fn(),
    };
  },
}));

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }));
vi.mock('../hooks/useThumbnailCache', () => ({
  useThumbnailCache: () => ({ loadThumbnails: vi.fn(), getThumbnail: vi.fn(), revision: 0 }),
}));
vi.mock('../hooks/useMediaQuery', () => ({ useMediaQuery: vi.fn(() => false) }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../api/files', () => ({ createFilesApi: () => ({ download: vi.fn(), batchDownload }) }));
vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ getMeta, search }),
}));
vi.mock('../components/layout/AppLayout', () => ({ AppLayout: ({ children, infoPanel, onSelectModeToggle, selectMode, viewMode }: { children: React.ReactNode; infoPanel: React.ReactNode; onSelectModeToggle?: () => void; selectMode?: boolean; viewMode?: string }) => <>{infoPanel}<output data-testid="view-mode">{viewMode}</output><button aria-label={selectMode ? 'mobile.done' : 'mobile.select'} onClick={onSelectModeToggle}>Toggle selection</button>{children}</> }));
vi.mock('../components/layout/Header', () => ({ Header: () => null }));
vi.mock('../components/layout/Sidebar', () => ({ Sidebar: () => null }));
vi.mock('../components/layout/InfoPanel', () => ({
  InfoPanel: ({ onTagFilter, metadata, selected, loading }: { onTagFilter?: (tag: string) => void; metadata?: { path?: string } | null; selected?: { path?: string; size?: number; size_fmt?: string; modified?: number } | null; loading?: boolean }) => (
    <>
      <output data-testid="metadata">{loading ? 'loading' : metadata?.path ?? 'none'}</output>
      <output data-testid="inspected-item">{selected?.path ?? 'none'}</output>
      <output data-testid="inspected-technical-fields">{JSON.stringify({ size: selected?.size, size_fmt: selected?.size_fmt, modified: selected?.modified })}</output>
      <button onClick={() => onTagFilter?.('featured')}>Filter tag</button>
      <button onClick={() => onTagFilter?.('first')}>Filter first tag</button>
      <button onClick={() => onTagFilter?.('second')}>Filter second tag</button>
    </>
  ),
}));
vi.mock('../components/files/Breadcrumb', () => ({ Breadcrumb: () => null }));
vi.mock('../components/files/FileToolbar', () => ({ FileToolbar: ({ selectedCount, activeTag, onClearTag, onDownloadSelected, isDownloadInFlight }: { selectedCount: number; activeTag?: string | null; onClearTag?: () => void; onDownloadSelected: () => void; isDownloadInFlight?: boolean }) => <><output data-testid="selected-count">{selectedCount}</output>{activeTag && <><output data-testid="active-tag">{activeTag}</output><button onClick={onClearTag}>Clear tag filter</button></>}{selectedCount > 0 && <button onClick={onDownloadSelected} disabled={isDownloadInFlight}>{isDownloadInFlight ? 'Downloading selected' : 'Download selected'}</button>}</> }));
vi.mock('../components/files/ProjectGrid', () => ({ ProjectGrid: (props: { items: Array<{ name: string; path: string; type: string; size?: number; size_fmt?: string; modified?: number }>; onSelect: (path: string) => void; onInspect: (item: { path: string; size?: number; size_fmt?: string; modified?: number }) => void; onZipSelect?: (path: string) => void; onDoubleClick: (item: { path: string }) => void; onContextMenu?: (event: React.MouseEvent, item: { path: string; type: string }) => void; selectionMode?: boolean }) => <><output data-testid="file-list">{props.items.map(item => item.name).join(',')}</output><output data-testid="file-list-technical-fields">{JSON.stringify(props.items.map(({ size, size_fmt, modified }) => ({ size, size_fmt, modified })))}</output><button onClick={() => props.selectionMode ? props.onSelect('asset.png') : props.onInspect(props.items[0]!)}>Select asset</button><button onClick={() => props.onZipSelect?.('asset.png')}>Select asset for ZIP</button><button onClick={() => props.onInspect(props.items[0]!)}>Inspect asset</button><button onClick={() => props.onDoubleClick({ path: 'asset.png' })}>Open asset</button><button onContextMenu={event => props.onContextMenu?.(event, props.items[0]!)}>Open item context menu</button></> }));
vi.mock('../components/files/ProjectList', () => ({ ProjectList: (props: { onSelect: (path: string) => void; onInspect: (item: { path: string }) => void; selectionMode?: boolean }) => <button onClick={() => props.selectionMode ? props.onSelect('asset.png') : props.onInspect({ path: 'asset.png' })}>List asset</button> }));
vi.mock('../components/ui/Skeleton', () => ({ Skeleton: () => null }));
vi.mock('../components/shares/ShareDialog', () => ({ ShareDialog: () => null }));

function LocationSearch() {
  return <output data-testid="location-search">{useLocation().search}</output>;
}

function NavigateToNewPath() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/browse?path=newer%2Furl')}>Navigate URL</button>;
}

function TestBrowsePage() {
  return <DownloadProgressProvider><BrowsePage /></DownloadProgressProvider>;
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
    localStorage.removeItem('am_view');
  });

  beforeEach(() => {
    localStorage.removeItem('am_view');
    listingItems = [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }];
    vi.mocked(useMediaQuery).mockReturnValue(false);
    search.mockReset();
    search.mockResolvedValue({ results: [{ path: 'tagged/item', name: 'item', type: 'file', extension: '', category: 'other' }] });
    getMeta.mockReset();
    getMeta.mockResolvedValue({ path: 'asset.png' });
    batchDownload.mockReset();
    batchDownload.mockResolvedValue(undefined);
    showToast.mockReset();
  });

  it('omits Detail from directory context menus while retaining it for files', () => {
    listingItems = [{ path: 'nested', name: 'nested', type: 'dir', extension: '', category: 'other', size_fmt: '', modified: 0 }];
    const { unmount } = render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.contextMenu(screen.getByRole('button', { name: 'Open item context menu' }));
    expect(screen.queryByRole('button', { name: 'action.detail' })).toBeNull();

    unmount();
    listingItems = [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }];
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);
    fireEvent.contextMenu(screen.getByRole('button', { name: 'Open item context menu' }));
    expect(screen.getByRole('button', { name: 'action.detail' })).toBeDefined();
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
    expect(search).toHaveBeenCalledWith('', 'featured');
    expect(screen.getByTestId('location-search').textContent).toBe('?path=original');
    fireEvent.click(screen.getByRole('button', { name: 'Clear tag filter' }));
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

  it('reports a selected ZIP download failure and clears progress', async () => {
    const pending = deferred<void>();
    batchDownload.mockReturnValueOnce(pending.promise);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download selected' }));

    expect(screen.getByRole('progressbar', { name: 'Download in progress' })).toBeDefined();
    pending.reject(new Error('ZIP failed'));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith('ZIP failed', 'error'));
    expect(screen.queryByRole('progressbar', { name: 'Download in progress' })).toBeNull();
  });

  it('clears a failed tag filter and restores the directory listing', async () => {
    search.mockRejectedValueOnce(new Error('Tag search failed'));
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    expect(screen.getByTestId('file-list').textContent).toBe('asset.png');
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('Failed to filter by tag', 'error'));
    expect(screen.queryByTestId('active-tag')).toBeNull();
    expect(screen.getByTestId('file-list').textContent).toBe('asset.png');
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

  it('ignores an older tag search that resolves after a newer one', async () => {
    const first = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
    const second = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
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
    await waitFor(() => expect(screen.getByTestId('active-tag').textContent).toBe('second'));

    first.resolve({ results: [{ path: 'older/item', name: 'older', type: 'file', extension: '', category: 'other' }] });
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('active-tag').textContent).toBe('second');
  });

  it('ignores a pending tag search after router search params change', async () => {
    const pending = deferred<{ results: Array<{ path: string; name: string; type: string; extension: string; category: string }> }>();
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

  it('inspects a desktop click without adding the item to the ZIP selection', async () => {
    const { useMediaQuery } = await import('../hooks/useMediaQuery');
    vi.mocked(useMediaQuery).mockReturnValue(false);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));

    expect(screen.getByTestId('inspected-item').textContent).toBe('asset.png');
    expect(screen.getByTestId('selected-count').textContent).toBe('0');
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

  it('serializes selected ZIP downloads until the active transfer finishes', async () => {
    const pending = deferred<void>();
    batchDownload.mockReturnValueOnce(pending.promise);
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    const downloadButton = screen.getByRole('button', { name: 'Download selected' });
    fireEvent.click(downloadButton);

    expect(batchDownload).toHaveBeenCalledTimes(1);
    expect((screen.getByRole('button', { name: 'Downloading selected' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Downloading selected' }));
    expect(batchDownload).toHaveBeenCalledTimes(1);

    pending.resolve();
    await waitFor(() => expect((screen.getByRole('button', { name: 'Download selected' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByRole('progressbar', { name: 'Download in progress' })).toBeNull();
  });

  it('applies workspace shortcuts outside editable elements and clears transient state before selection', async () => {
    render(<MemoryRouter initialEntries={['/browse']}><TestBrowsePage /></MemoryRouter>);

    fireEvent.keyDown(document, { key: 'g' });
    expect(screen.getByTestId('view-mode').textContent).toBe('list');
    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    await waitFor(() => expect(screen.getByTestId('active-tag').textContent).toBe('featured'));
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
});
