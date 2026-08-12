// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { collectionMock, toggleFavoriteMock, i18nMock, authMock } = vi.hoisted(() => ({
  collectionMock: vi.fn(),
  toggleFavoriteMock: vi.fn(),
  i18nMock: { t: (key: string) => key },
  authMock: { api: {} },
}));

let invalidationCallback: (() => void) | undefined;

vi.mock('../api/gallery', () => ({
  createGalleryApi: () => ({ collection: collectionMock }),
}));
// Stable references: the page memoizes galleryApi on `api` and refetches when
// `t` changes, so fresh objects per render would restart the request loop.
vi.mock('../hooks/useAuth', () => ({ useAuth: () => authMock }));
vi.mock('../hooks/useFavorites', () => ({
  useFavorites: () => ({ isFavorite: () => false, toggleFavorite: toggleFavoriteMock }),
}));
vi.mock('../hooks/useInvalidation', () => ({
  useInvalidation: (_domains: readonly string[], callback: () => void) => { invalidationCallback = callback; },
}));
// Stable reference: the page's fetch effect depends on `t`, so a fresh
// object per render would restart the request loop forever.
vi.mock('../hooks/useI18n', () => ({ useI18n: () => i18nMock }));
vi.mock('../components/gallery/GalleryLayout', () => ({ GalleryLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../components/gallery/GalleryCard', () => ({ GalleryCard: () => null }));
vi.mock('../components/gallery/GalleryEmptyState', () => ({
  GalleryEmptyState: ({ title, description, onRetry }: { title: string; description: string; onRetry?: () => void }) => (
    <div><span>{title}</span><span>{description}</span>{onRetry && <button type="button" onClick={onRetry}>retry</button>}</div>
  ),
}));
vi.mock('../components/gallery/GalleryTiledGrid', () => ({ GalleryTiledGrid: () => null }));
vi.mock('../components/gallery/GalleryViewControls', () => ({ GalleryViewControls: () => null }));

import GalleryCollectionPage from './GalleryCollectionPage';

function collectionResponse(name: string) {
  return {
    collection: { path: 'projects/hero', name, kind: 'project', artwork_count: 3, size_fmt: '1.2 MB' },
    children: [],
    entries: [],
  };
}

describe('GalleryCollectionPage', () => {
  beforeEach(() => {
    collectionMock.mockReset();
    toggleFavoriteMock.mockReset();
    invalidationCallback = undefined;
  });

  afterEach(() => cleanup());

  it('renders the collection heading once loaded', async () => {
    collectionMock.mockResolvedValue(collectionResponse('Hero Pack'));
    render(
      <MemoryRouter initialEntries={['/gallery/collection?path=projects/hero']}>
        <GalleryCollectionPage />
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: 'Hero Pack' })).toBeDefined();
    expect(collectionMock).toHaveBeenCalledWith('projects/hero', { sort: 'updated', kind: 'all' }, expect.any(AbortSignal));
  });

  it('shows the unavailable state with retry on failure', async () => {
    collectionMock.mockRejectedValue(new Error('boom'));
    render(
      <MemoryRouter initialEntries={['/gallery/collection?path=projects/hero']}>
        <GalleryCollectionPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText('gallery.collection_unavailable')).toBeDefined();
    fireRetry();
  });

  it('shows the missing state when the collection is absent', async () => {
    collectionMock.mockResolvedValue({ collection: null, children: [], entries: [] });
    render(
      <MemoryRouter initialEntries={['/gallery/collection?path=projects/hero']}>
        <GalleryCollectionPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText('gallery.collection_missing')).toBeDefined();
  });

  it('refetches when realtime invalidation fires', async () => {
    collectionMock.mockResolvedValue(collectionResponse('Hero Pack'));
    render(
      <MemoryRouter initialEntries={['/gallery/collection?path=projects/hero']}>
        <GalleryCollectionPage />
      </MemoryRouter>,
    );
    await screen.findByRole('heading', { name: 'Hero Pack' });
    expect(collectionMock).toHaveBeenCalledTimes(1);
    await waitFor(() => { invalidationCallback?.(); });
    expect(collectionMock).toHaveBeenCalledTimes(2);
  });

  function fireRetry() {
    const button = screen.getByText('retry');
    button.click();
  }
});
