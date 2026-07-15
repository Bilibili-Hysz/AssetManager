// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BrowsePage from './BrowsePage';

const search = vi.fn();
const getMeta = vi.fn();

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ api: {}, user: null }),
}));

vi.mock('../hooks/useProjects', () => ({
  useProjects: (initialPath: string) => {
    const [currentPath, navigateTo] = useState(initialPath);
    return {
      data: { items: [{ path: 'asset.png', name: 'asset.png', type: 'file', extension: '.png', category: 'image', size_fmt: '1 KB', modified: 0 }] },
      isLoading: false,
      error: null,
      currentPath,
      sort: { sort: 'name', order: 'asc' },
      navigateTo,
      setSort: vi.fn(),
      refresh: vi.fn(),
    };
  },
}));

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }));
vi.mock('../hooks/useThumbnailCache', () => ({
  useThumbnailCache: () => ({ loadThumbnails: vi.fn(), getThumbnail: vi.fn(), revision: 0 }),
}));
vi.mock('../hooks/useMediaQuery', () => ({ useMediaQuery: vi.fn(() => true) }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('../api/files', () => ({ createFilesApi: () => ({ download: vi.fn(), batchDownload: vi.fn() }) }));
vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ getMeta, search }),
}));
vi.mock('../components/layout/AppLayout', () => ({ AppLayout: ({ children, infoPanel, onSelectModeToggle, selectMode }: { children: React.ReactNode; infoPanel: React.ReactNode; onSelectModeToggle?: () => void; selectMode?: boolean }) => <>{infoPanel}<button aria-label={selectMode ? 'mobile.done' : 'mobile.select'} onClick={onSelectModeToggle}>Toggle selection</button>{children}</> }));
vi.mock('../components/layout/Header', () => ({ Header: () => null }));
vi.mock('../components/layout/Sidebar', () => ({ Sidebar: () => null }));
vi.mock('../components/layout/InfoPanel', () => ({
  InfoPanel: ({ onTagClick, metadata, loading }: { onTagClick?: (tag: string) => void; metadata?: { path?: string } | null; loading?: boolean }) => (
    <>
      <output data-testid="metadata">{loading ? 'loading' : metadata?.path ?? 'none'}</output>
      <button onClick={() => onTagClick?.('featured')}>Filter tag</button>
      <button onClick={() => onTagClick?.('first')}>Filter first tag</button>
      <button onClick={() => onTagClick?.('second')}>Filter second tag</button>
    </>
  ),
}));
vi.mock('../components/files/Breadcrumb', () => ({ Breadcrumb: () => null }));
vi.mock('../components/files/FileToolbar', () => ({ FileToolbar: ({ selectedCount }: { selectedCount: number }) => <output data-testid="selected-count">{selectedCount}</output> }));
vi.mock('../components/files/ProjectGrid', () => ({ ProjectGrid: (props: { onSelect: (path: string) => void; onCardClick?: (item: { path: string }) => void; onDoubleClick: (item: { path: string }) => void; selectionMode?: boolean }) => <><button onClick={() => { props.onSelect('asset.png'); if (!props.selectionMode) props.onCardClick?.({ path: 'asset.png' }); }}>Select asset</button><button onClick={() => props.onDoubleClick({ path: 'asset.png' })}>Open asset</button></> }));
vi.mock('../components/files/ProjectList', () => ({ ProjectList: (props: { onSelect: (path: string) => void; onCardClick?: (item: { path: string }) => void; selectionMode?: boolean }) => <button onClick={() => { props.onSelect('asset.png'); if (!props.selectionMode) props.onCardClick?.({ path: 'asset.png' }); }}>List asset</button> }));
vi.mock('../components/ui/Skeleton', () => ({ Skeleton: () => null }));
vi.mock('../components/shares/ShareDialog', () => ({ ShareDialog: () => null }));

function LocationSearch() {
  return <output data-testid="location-search">{useLocation().search}</output>;
}

function NavigateToNewPath() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/browse?path=newer%2Furl')}>Navigate URL</button>;
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
  afterEach(cleanup);

  beforeEach(() => {
    search.mockReset();
    search.mockResolvedValue({ results: [{ path: 'tagged/item' }] });
    getMeta.mockReset();
    getMeta.mockResolvedValue({ path: 'asset.png' });
  });

  it('updates the path query to the selected tag result', async () => {
    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <BrowsePage />
        <LocationSearch />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));

    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=tagged%2Fitem'));
  });

  it('only selects an asset after mobile selection mode is enabled', async () => {
    const { useMediaQuery } = await import('../hooks/useMediaQuery');
    vi.mocked(useMediaQuery).mockReturnValue(true);
    render(<MemoryRouter initialEntries={['/browse']}><BrowsePage /></MemoryRouter>);
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
    render(<MemoryRouter initialEntries={['/browse']}><BrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    expect(getMeta).not.toHaveBeenCalled();
    cleanup();
    localStorage.setItem('am_view', 'list');
    render(<MemoryRouter initialEntries={['/browse']}><BrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'mobile.select' }));
    fireEvent.click(screen.getByRole('button', { name: 'List asset' }));
    expect(getMeta).not.toHaveBeenCalled();
    localStorage.removeItem('am_view');
  });

  it('ignores stale metadata responses and cleanup from an older card', async () => {
    const first = deferred<{ path: string }>();
    const second = deferred<{ path: string }>();
    getMeta.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(<MemoryRouter initialEntries={['/browse']}><BrowsePage /></MemoryRouter>);
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
    render(<MemoryRouter initialEntries={['/browse']}><BrowsePage /></MemoryRouter>);
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
    const view = render(<MemoryRouter initialEntries={['/browse']}><BrowsePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Select asset' }));
    const signal = getMeta.mock.calls[getMeta.mock.calls.length - 1]?.[1] as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    pending.resolve({ path: 'stale' });
  });

  it('ignores an older tag search that resolves after a newer one', async () => {
    const first = deferred<{ results: Array<{ path: string }> }>();
    const second = deferred<{ results: Array<{ path: string }> }>();
    search.mockReset();
    search.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <BrowsePage />
        <LocationSearch />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter first tag' }));
    fireEvent.click(screen.getByRole('button', { name: 'Filter second tag' }));

    second.resolve({ results: [{ path: 'newer/item' }] });
    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=newer%2Fitem'));

    first.resolve({ results: [{ path: 'older/item' }] });
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('location-search').textContent).toBe('?path=newer%2Fitem');
  });

  it('ignores a pending tag search after router search params change', async () => {
    const pending = deferred<{ results: Array<{ path: string }> }>();
    search.mockReset();
    search.mockReturnValueOnce(pending.promise);

    render(
      <MemoryRouter initialEntries={['/browse?path=original']}>
        <BrowsePage />
        <NavigateToNewPath />
        <LocationSearch />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Filter tag' }));
    fireEvent.click(screen.getByRole('button', { name: 'Navigate URL' }));
    await waitFor(() => expect(screen.getByTestId('location-search').textContent).toBe('?path=newer%2Furl'));

    pending.resolve({ results: [{ path: 'stale/tag-result' }] });
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('location-search').textContent).toBe('?path=newer%2Furl');
  });
});
