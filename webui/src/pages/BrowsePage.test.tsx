// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
vi.mock('../components/layout/InfoPanel', () => ({ InfoPanel: ({ onTagClick }: { onTagClick?: (tag: string) => void }) => <button onClick={() => onTagClick?.('featured')}>Filter tag</button> }));
vi.mock('../components/files/Breadcrumb', () => ({ Breadcrumb: () => null }));
vi.mock('../components/files/FileToolbar', () => ({ FileToolbar: () => null }));
vi.mock('../components/files/ProjectGrid', () => ({ ProjectGrid: () => null }));
vi.mock('../components/files/ProjectList', () => ({ ProjectList: () => null }));
vi.mock('../components/ui/Skeleton', () => ({ Skeleton: () => null }));
vi.mock('../components/shares/ShareDialog', () => ({ ShareDialog: () => null }));

function LocationSearch() {
  return <output data-testid="location-search">{useLocation().search}</output>;
}

describe('BrowsePage', () => {
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
});
