// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BrowsableItem } from '../../types/api';

vi.mock('../../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

import { MasonryView } from './MasonryView';

const fileItem: BrowsableItem = {
  name: 'hero.png', path: 'projects/hero.png', type: 'file',
  extension: '.png', category: 'image', thumbnail_url: '/api/thumbnails/projects/hero.png',
};
const dirItem: BrowsableItem = {
  name: 'assets', path: 'projects/assets', type: 'dir',
  extension: '', category: 'folder',
};

describe('MasonryView', () => {
  afterEach(() => cleanup());

  it('renders every item with its name', () => {
    render(<MasonryView items={[fileItem, dirItem]} />);
    expect(screen.getByText('hero.png')).toBeDefined();
    expect(screen.getByText('assets')).toBeDefined();
  });

  it('inspects files on click and navigates directories on mobile', () => {
    const onInspect = vi.fn();
    const onNavigate = vi.fn();
    render(
      <MasonryView
        items={[fileItem, dirItem]}
        isMobile
        onInspect={onInspect}
        onNavigate={onNavigate}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'hero.png' }));
    expect(onInspect).toHaveBeenCalledWith(fileItem);
    fireEvent.click(screen.getByRole('button', { name: 'assets' }));
    expect(onNavigate).toHaveBeenCalledWith('projects/assets');
    expect(onInspect).toHaveBeenCalledTimes(1);
  });

  it('inspects directories on click when not mobile', () => {
    const onInspect = vi.fn();
    const onNavigate = vi.fn();
    render(<MasonryView items={[dirItem]} onInspect={onInspect} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole('button', { name: 'assets' }));
    expect(onInspect).toHaveBeenCalledWith(dirItem);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('selects items in selection mode instead of opening', () => {
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    render(
      <MasonryView
        items={[fileItem]}
        selectionMode
        selected={new Set(['projects/hero.png'])}
        onSelect={onSelect}
        onInspect={onInspect}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'hero.png' }));
    expect(onSelect).toHaveBeenCalledWith('projects/hero.png');
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('toggles favorites for dirs and images', () => {
    const onToggleFavorite = vi.fn();
    const isFavorite = vi.fn((path: string) => path === 'projects/hero.png');
    render(<MasonryView items={[fileItem, dirItem]} onToggleFavorite={onToggleFavorite} isFavorite={isFavorite} />);
    const favButtons = screen.getAllByRole('button', { name: /gallery\.(add|remove)_favorite/ });
    expect(favButtons.length).toBe(2);
    fireEvent.click(favButtons[0]!);
    expect(onToggleFavorite).toHaveBeenCalledWith('projects/hero.png');
  });

  it('opens double-clicked directories and inspects files', () => {
    const onDoubleClick = vi.fn();
    const onInspect = vi.fn();
    render(
      <MasonryView
        items={[fileItem, dirItem]}
        onDoubleClick={onDoubleClick}
        onInspect={onInspect}
      />,
    );
    fireEvent.doubleClick(screen.getByRole('button', { name: 'hero.png' }));
    expect(onDoubleClick).toHaveBeenCalledWith(fileItem);
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('hydrates visible directories and renders their cover thumbnails', () => {
    // Regression: masonry mode never received onDirectoryVisible, so with a
    // summaries=false listing directory cards had no cover and no size — the
    // only view whose cards stayed empty.
    class FakeIntersectionObserver {
      static instances: FakeIntersectionObserver[] = [];
      callback: IntersectionObserverCallback;
      observed: Element[] = [];
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback;
        FakeIntersectionObserver.instances.push(this);
      }
      observe(target: Element) {
        this.observed.push(target);
        this.callback(
          this.observed.map(entry => ({ isIntersecting: true, target: entry }) as unknown as IntersectionObserverEntry),
          this as unknown as IntersectionObserver,
        );
      }
      disconnect() { this.observed = []; }
      unobserve() {}
    }
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);

    const onDirectoryVisible = vi.fn();
    render(
      <MasonryView
        items={[fileItem, dirItem]}
        getThumbnail={path => (path === 'projects/assets' ? '/api/thumbnails/projects/assets' : undefined)}
        onDirectoryVisible={onDirectoryVisible}
      />,
    );

    const observedPaths = FakeIntersectionObserver.instances
      .flatMap(instance => instance.observed)
      .map(node => node.getAttribute('data-directory-path'));
    expect(observedPaths).toEqual(['projects/assets']);
    expect(onDirectoryVisible).toHaveBeenCalledWith('projects/assets');

    // alt="" images map to the presentation role; assert on src instead.
    const sources = Array.from(document.querySelectorAll('img')).map(img => img.getAttribute('src'));
    expect(sources).toContain('/api/thumbnails/projects/assets');

    vi.unstubAllGlobals();
  });
});
