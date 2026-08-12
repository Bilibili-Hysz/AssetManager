// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));
vi.mock('../layout/AppHeader', () => ({
  AppHeader: () => <div data-testid="app-header" />,
}));

import { GalleryEmptyState } from './GalleryEmptyState';
import { GalleryLayout } from './GalleryLayout';
import { GallerySection } from './GallerySection';
import { GalleryTiledGrid } from './GalleryTiledGrid';
import { galleryMediaMode, GalleryViewControls, readGalleryView, GALLERY_VIEW_STORAGE_KEY } from './GalleryViewControls';

describe('GallerySection', () => {
  it('renders the title, optional action, and children', () => {
    render(
      <GallerySection title="Collections" action={<button type="button">All</button>}>
        <div>content</div>
      </GallerySection>,
    );
    expect(screen.getByText('Collections')).toBeDefined();
    expect(screen.getByText('All')).toBeDefined();
    expect(screen.getByText('content')).toBeDefined();
  });
});

describe('GalleryEmptyState', () => {
  it('renders title/description with retry only when provided', () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <MemoryRouter>
        <GalleryEmptyState title="Empty" description="Nothing here" onRetry={onRetry} />
      </MemoryRouter>,
    );
    expect(screen.getByText('Empty')).toBeDefined();
    expect(screen.getByText('Nothing here')).toBeDefined();
    fireEvent.click(screen.getByText('gallery.retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(
      <MemoryRouter>
        <GalleryEmptyState title="Empty" description="Nothing here" />
      </MemoryRouter>,
    );
    expect(screen.queryByText('gallery.retry')).toBeNull();
  });
});

describe('GalleryLayout', () => {
  it('renders the shell with the AppHeader and children', () => {
    render(
      <MemoryRouter initialEntries={['/gallery?path=projects']}>
        <GalleryLayout><div>body</div></GalleryLayout>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('app-header')).toBeDefined();
    expect(screen.getByText('body')).toBeDefined();
  });
});

describe('GalleryTiledGrid', () => {
  it('renders one tile per entry via the render prop', () => {
    const entries = [
      { path: 'a', name: 'A' },
      { path: 'b', name: 'B' },
    ] as Array<{ path: string; name: string }>;
    render(
      <GalleryTiledGrid entries={entries as never}>
        {entry => <div>{entry.name}</div>}
      </GalleryTiledGrid>,
    );
    expect(screen.getByText('A')).toBeDefined();
    expect(screen.getByText('B')).toBeDefined();
  });
});

describe('GalleryViewControls', () => {
  it('derives media mode from view mode', () => {
    expect(galleryMediaMode('grid')).toBe('uniform');
    expect(galleryMediaMode('compact')).toBe('compact');
    expect(galleryMediaMode('masonry')).toBe('square');
  });

  it('reads the persisted view mode and falls back to masonry', () => {
    expect(readGalleryView()).toBe('masonry');
    localStorage.setItem(GALLERY_VIEW_STORAGE_KEY, 'grid');
    expect(readGalleryView()).toBe('grid');
    localStorage.setItem(GALLERY_VIEW_STORAGE_KEY, 'bogus');
    expect(readGalleryView()).toBe('masonry');
  });

  it('notifies the parent on view change', () => {
    const onChange = vi.fn();
    render(<GalleryViewControls value="grid" onChange={onChange} />);
    // Three mode buttons; clicking masonry emits, clicking the active grid
    // mode is still reported (the parent decides whether to ignore it).
    const masonry = screen.getByRole('button', { name: 'gallery.view_masonry' });
    const grid = screen.getByRole('button', { name: 'gallery.view_grid' });
    expect(screen.getByRole('button', { name: 'gallery.view_compact' })).toBeDefined();
    fireEvent.click(grid);
    expect(onChange).toHaveBeenCalledWith('grid');
    fireEvent.click(masonry);
    expect(onChange).toHaveBeenCalledWith('masonry');
  });
});
