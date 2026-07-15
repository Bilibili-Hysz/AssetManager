// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BrowsePage from './BrowsePage';

const search = vi.fn();

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ api: {}, user: null }),
}));

vi.mock('../hooks/useProjects', () => ({
  useProjects: (initialPath: string) => ({
    data: { items: [] },
    isLoading: false,
    error: null,
    currentPath: initialPath,
    sort: { sort: 'name', order: 'asc' },
    navigateTo: vi.fn(),
    setSort: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }));
vi.mock('../hooks/useThumbnailCache', () => ({
  useThumbnailCache: () => ({ loadThumbnails: vi.fn(), getThumbnail: vi.fn(), revision: 0 }),
}));
vi.mock('../hooks/useMediaQuery', () => ({ useMediaQuery: () => false }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('../api/files', () => ({ createFilesApi: () => ({ download: vi.fn(), batchDownload: vi.fn() }) }));
vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ getMeta: vi.fn(), search }),
}));
vi.mock('../components/layout/AppLayout', () => ({ AppLayout: ({ children, infoPanel }: { children: React.ReactNode; infoPanel: React.ReactNode }) => <>{infoPanel}{children}</> }));
vi.mock('../components/layout/Header', () => ({ Header: () => null }));
vi.mock('../components/layout/Sidebar', () => ({ Sidebar: () => null }));
vi.mock('../components/layout/InfoPanel', () => ({
  InfoPanel: ({ onTagClick }: { onTagClick?: (tag: string) => void }) => (
    <>
      <button onClick={() => onTagClick?.('featured')}>Filter tag</button>
      <button onClick={() => onTagClick?.('first')}>Filter first tag</button>
      <button onClick={() => onTagClick?.('second')}>Filter second tag</button>
    </>
  ),
}));
vi.mock('../components/files/Breadcrumb', () => ({ Breadcrumb: () => null }));
vi.mock('../components/files/FileToolbar', () => ({ FileToolbar: () => null }));
vi.mock('../components/files/ProjectGrid', () => ({ ProjectGrid: () => null }));
vi.mock('../components/files/ProjectList', () => ({ ProjectList: () => null }));
vi.mock('../components/ui/Skeleton', () => ({ Skeleton: () => null }));
vi.mock('../components/shares/ShareDialog', () => ({ ShareDialog: () => null }));

function LocationSearch() {
  return <output data-testid="location-search">{useLocation().search}</output>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(resolvePromise => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe('BrowsePage', () => {
  afterEach(cleanup);

  beforeEach(() => {
    search.mockReset();
    search.mockResolvedValue({ results: [{ path: 'tagged/item' }] });
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
});
