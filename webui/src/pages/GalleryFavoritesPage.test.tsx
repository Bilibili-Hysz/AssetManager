// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GalleryEntry } from '../types/api';

const { favoritesMock, toggleFavoriteMock, refreshMock, i18nMock } = vi.hoisted(() => ({
  favoritesMock: { items: [] as GalleryEntry[], loading: false, error: null as string | null },
  toggleFavoriteMock: vi.fn(),
  refreshMock: vi.fn(),
  i18nMock: { t: (key: string) => key },
}));

vi.mock('../hooks/useFavorites', () => ({
  useFavorites: () => ({
    items: favoritesMock.items,
    loading: favoritesMock.loading,
    error: favoritesMock.error,
    isFavorite: () => false,
    toggleFavorite: toggleFavoriteMock,
    refresh: refreshMock,
  }),
}));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => i18nMock }));
vi.mock('../components/gallery/GalleryLayout', () => ({ GalleryLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../components/gallery/GalleryCard', () => ({ GalleryCard: () => null }));
vi.mock('../components/gallery/GalleryEmptyState', () => ({
  GalleryEmptyState: ({ title, onRetry }: { title: string; onRetry?: () => void }) => (
    <div><span>{title}</span>{onRetry && <button type="button" onClick={onRetry}>retry</button>}</div>
  ),
}));
vi.mock('../components/gallery/GalleryTiledGrid', () => ({ GalleryTiledGrid: () => null }));
vi.mock('../components/gallery/GalleryViewControls', () => ({
  GalleryViewControls: () => null,
  readGalleryView: () => 'masonry',
  galleryMediaMode: () => 'square',
}));

import GalleryFavoritesPage from './GalleryFavoritesPage';

const entry: GalleryEntry = {
  name: 'hero', path: 'projects/hero', kind: 'project', parent_path: 'projects', modified: 100,
};

describe('GalleryFavoritesPage', () => {
  beforeEach(() => {
    favoritesMock.items = [];
    favoritesMock.loading = false;
    favoritesMock.error = null;
    toggleFavoriteMock.mockReset();
    refreshMock.mockReset();
  });

  afterEach(() => cleanup());

  it('shows the skeleton while loading', () => {
    favoritesMock.loading = true;
    render(<MemoryRouter><GalleryFavoritesPage /></MemoryRouter>);
    expect(screen.getByRole('status')).toBeDefined();
  });

  it('shows the unavailable state with a retry that refreshes', () => {
    favoritesMock.error = 'boom';
    render(<MemoryRouter><GalleryFavoritesPage /></MemoryRouter>);
    expect(screen.getByText('gallery.favorites_unavailable')).toBeDefined();
    fireEvent.click(screen.getByText('retry'));
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it('shows the empty state when there are no favorites', () => {
    render(<MemoryRouter><GalleryFavoritesPage /></MemoryRouter>);
    expect(screen.getByText('gallery.no_favorites')).toBeDefined();
  });

  it('renders the favorites grid with a count badge when items exist', () => {
    favoritesMock.items = [entry];
    render(<MemoryRouter><GalleryFavoritesPage /></MemoryRouter>);
    // The count appears in both the heading badge and the toolbar meta.
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(1);
  });
});
