// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import GalleryHomePage from './GalleryHomePage';

const { apiMock, homeMock, toggleFavoriteMock, useInvalidationMock, translateMock } = vi.hoisted(() => ({
  apiMock: {},
  homeMock: vi.fn(),
  toggleFavoriteMock: vi.fn(),
  useInvalidationMock: vi.fn(),
  translateMock: (key: string, value?: number) => ({
    'gallery.latest_collection': 'Latest collection',
    'gallery.latest_project': 'Latest project',
    'gallery.open_collection': 'Open collection',
    'gallery.open_project': 'Open project',
    'gallery.open_workspace_action': 'Open workspace',
    'gallery.save_collection': 'Save collection',
    'gallery.save_project': 'Save project',
    'gallery.saved': 'Saved',
    'gallery.works_to_explore': `${value ?? 0} works to explore`,
    'gallery.visual_library': 'Visual library',
    'gallery.visual_library_description': 'Visual library description',
    'gallery.loading': 'Loading',
    'gallery.unavailable': 'Unavailable',
    'gallery.retry': 'Retry',
    'gallery.no_visual_assets': 'No visual assets',
    'gallery.inspect_workspace': 'Inspect workspace',
    'gallery.collections': 'Collections',
    'gallery.view_all': 'View all',
    'gallery.projects': 'Projects',
    'gallery.latest_works': 'Latest works',
    'gallery.total_works': `${value ?? 0} works`,
    'gallery.no_root_works': 'No root works',
    'gallery.load_failed': 'Failed to load gallery',
  }[key] ?? key),
}));

let invalidationCallback: ((event: unknown) => void) | undefined;
let favorite = false;

vi.mock('../api/gallery', () => ({
  createGalleryApi: () => ({ home: homeMock }),
}));
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api: apiMock, identityGeneration: 0 }) }));
vi.mock('../hooks/useFavorites', () => ({
  useFavorites: () => ({
    isFavorite: () => favorite,
    toggleFavorite: toggleFavoriteMock,
  }),
}));
vi.mock('../hooks/useInvalidation', () => ({
  useInvalidation: (_domains: readonly string[], callback: (event: unknown) => void) => {
    invalidationCallback = callback;
  },
}));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: translateMock }) }));
vi.mock('../components/gallery/GalleryLayout', () => ({ GalleryLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../components/gallery/GalleryCard', () => ({ GalleryCard: () => null }));
vi.mock('../components/gallery/GalleryEmptyState', () => ({ GalleryEmptyState: () => null }));
vi.mock('../components/gallery/GallerySection', () => ({ GallerySection: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../components/gallery/GalleryTiledGrid', () => ({ GalleryTiledGrid: ({ children }: { children: (entry: never) => React.ReactNode }) => <>{children({} as never)}</> }));
vi.mock('../components/gallery/GalleryViewControls', () => ({
  GalleryViewControls: () => null,
  galleryMediaMode: () => 'cover',
}));

const homeResponse = (name: string) => ({
  featured: { path: 'collections/featured', name, kind: 'collection', artwork_count: 3, cover_url: null },
  collections: [],
  projects: [],
  recent: [],
  stats: { artworks: 3 },
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(value => { resolve = value; });
  return { promise, resolve };
}

function renderHome() {
  render(<QueryCacheProvider><MemoryRouter><GalleryHomePage /></MemoryRouter></QueryCacheProvider>);
}

describe('GalleryHomePage', () => {
  beforeEach(() => {
    favorite = false;
    invalidationCallback = undefined;
    homeMock.mockReset();
    toggleFavoriteMock.mockReset();
    useInvalidationMock.mockReset();
  });

  afterEach(() => cleanup());

  it('restores the featured hero favorite shortcut while preserving workspace navigation', async () => {
    homeMock.mockResolvedValue(homeResponse('Featured collection'));
    renderHome();

    expect(await screen.findByRole('heading', { name: 'Featured collection' })).toBeDefined();
    const favoriteButton = screen.getByRole('button', { name: 'Save collection' });
    expect(favoriteButton.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(favoriteButton);
    expect(toggleFavoriteMock).toHaveBeenCalledWith('collections/featured');
  });

  it('ignores a stale home response after realtime invalidation starts a newer request', async () => {
    const first = deferred<ReturnType<typeof homeResponse>>();
    const second = deferred<ReturnType<typeof homeResponse>>();
    homeMock.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    renderHome();

    await waitFor(() => expect(invalidationCallback).toBeDefined());
    // null event = invalidate everything, mirroring the shared cache hook's
    // shouldInvalidate semantics for reconnects / full invalidations.
    act(() => { invalidationCallback?.(null); });
    second.resolve(homeResponse('Fresh collection'));
    expect(await screen.findByRole('heading', { name: 'Fresh collection' })).toBeDefined();

    first.resolve(homeResponse('Stale collection'));
    await act(async () => { await first.promise; });
    expect(screen.getByRole('heading', { name: 'Fresh collection' })).toBeDefined();
    expect(screen.queryByRole('heading', { name: 'Stale collection' })).toBeNull();
  });

  it('shows the building state and polls until the backend projection is ready', async () => {
    vi.useFakeTimers();
    homeMock
      .mockResolvedValueOnce({ building: true })
      .mockResolvedValueOnce(homeResponse('Ready collection'));
    renderHome();

    // First response reports building; the page shows the building notice.
    await act(async () => {});
    expect(screen.getByText('gallery.building')).toBeDefined();

    // The 5s poll timer refetches; the second response resolves the data.
    act(() => { vi.advanceTimersByTime(5000); });
    await act(async () => {});
    expect(screen.getByRole('heading', { name: 'Ready collection' })).toBeDefined();
    expect(screen.queryByText('gallery.building')).toBeNull();
    vi.useRealTimers();
  });
});