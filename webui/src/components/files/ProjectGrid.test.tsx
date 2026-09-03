// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectGrid } from './ProjectGrid';
import { SINGLE_CLICK_DELAY_MS } from './ProjectCard';

describe('ProjectGrid', () => {
  it('uses container-driven adaptive columns', () => {
    render(<ProjectGrid items={[]} selected={new Set()} onSelect={vi.fn()} thumbnailMap={{}} />);

    const grid = screen.getByTestId('project-grid');
    expect(grid.className).toContain('grid-cols-[repeat(auto-fill,minmax(168px,1fr))]');
    expect(grid.className).toContain('w-full');
    expect(grid.className).toContain('min-w-0');
  });

  it('keeps the grid host shrinkable while filling the available canvas width', () => {
    render(<ProjectGrid items={[]} selected={new Set()} onSelect={vi.fn()} thumbnailMap={{}} />);

    expect(screen.getByTestId('project-grid').className).toContain(
      'grid-cols-[repeat(auto-fill,minmax(168px,1fr))]',
    );
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders tag search results without fabricated technical fields', () => {
    render(
      <ProjectGrid
        items={[{ name: 'tagged.png', path: 'tagged.png', type: 'file', extension: '.png', category: 'image' }]}
        selected={new Set()}
        onSelect={() => {}}
        thumbnailMap={{}}
      />,
    );

    expect(screen.getByRole('button', { name: 'tagged.png' })).toBeDefined();
    expect(screen.queryByText('0 B')).toBeNull();
  });

  it('uses the visible ZIP control for selection while a card click only inspects', () => {
    vi.useFakeTimers();
    const onZipSelect = vi.fn();
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    render(
      <ProjectGrid
        items={[{ name: 'asset.png', path: 'asset.png', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.png', category: 'image' }]}
        selected={new Set()}
        onSelect={onSelect}
        onZipSelect={onZipSelect}
        onInspect={onInspect}
        thumbnailMap={{}}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Select asset.png for ZIP download' }));
    expect(onZipSelect).toHaveBeenCalledWith('asset.png');
    expect(onInspect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'asset.png, 1 B' }));
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({ path: 'asset.png' }));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('keeps desktop directory clicks in BrowsePage callbacks and opens on double click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const onNavigate = vi.fn();
    const onSelect = vi.fn();
    const onZipSelect = vi.fn();
    render(
      <ProjectGrid
        items={[{ name: 'nested', path: 'parent/nested', type: 'dir', extension: '', category: 'other' }]}
        selected={new Set()}
        onSelect={onSelect}
        onZipSelect={onZipSelect}
        onInspect={onInspect}
        onDoubleClick={onDoubleClick}
        onNavigate={onNavigate}
        thumbnailMap={{}}
      />,
    );

    const directory = screen.getByRole('button', { name: 'nested' });
    fireEvent.click(directory);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledTimes(1);
    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({ path: 'parent/nested' }));
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.doubleClick(directory);
    fireEvent.keyDown(directory, { key: 'Enter' });

    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({ path: 'parent/nested' }));
    expect(onSelect).not.toHaveBeenCalled();
    expect(onDoubleClick).toHaveBeenCalledTimes(2);
    expect(onDoubleClick).toHaveBeenCalledWith(expect.objectContaining({ path: 'parent/nested' }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(onZipSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Select nested for ZIP download' })).toBeNull();
  });

  it('preserves project metadata in inspect and open payloads', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const onSelect = vi.fn();
    const project = { name: 'Project', path: 'Project', type: 'dir' as const, extension: '', category: 'other', is_project: true };
    render(<ProjectGrid items={[project]} selected={new Set()} onSelect={onSelect} onInspect={onInspect} onDoubleClick={onDoubleClick} thumbnailMap={{}} />);

    const button = screen.getByRole('button', { name: 'Project' });
    fireEvent.click(button);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    fireEvent.doubleClick(button);

    expect(onInspect).toHaveBeenCalledWith(project);
    expect(onSelect).not.toHaveBeenCalled();
    expect(onDoubleClick).toHaveBeenCalledWith(project);
  });

  it('inspects the complete item on a normal desktop click', () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    const project = { name: 'Project', path: 'Project', type: 'dir' as const, extension: '', category: 'other', is_project: true };
    render(<ProjectGrid items={[project]} selected={new Set()} onSelect={onSelect} onInspect={onInspect} thumbnailMap={{}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Project' }));
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);

    expect(onInspect).toHaveBeenCalledWith(project);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('toggles selection in selection mode without inspecting', () => {
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectGrid items={[item]} selected={new Set()} onSelect={onSelect} onInspect={onInspect} selectionMode thumbnailMap={{}} />);

    fireEvent.click(screen.getByRole('button', { name: 'asset.png' }));

    expect(onSelect).toHaveBeenCalledWith('asset.png');
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('selects the path on Enter in selection mode instead of opening', () => {
    const onSelect = vi.fn();
    const onDoubleClick = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectGrid items={[item]} selected={new Set()} onSelect={onSelect} onInspect={vi.fn()} onDoubleClick={onDoubleClick} selectionMode thumbnailMap={{}} />);

    fireEvent.keyDown(screen.getByRole('button', { name: 'asset.png' }), { key: 'Enter' });

    expect(onSelect).toHaveBeenCalledWith('asset.png');
    expect(onDoubleClick).not.toHaveBeenCalled();
  });

  it('navigates a directory on mobile single click', () => {
    vi.useFakeTimers();
    const onNavigate = vi.fn();
    const onInspect = vi.fn();
    render(<ProjectGrid items={[{ name: 'Assets', path: 'Assets', type: 'dir', extension: '', category: 'other' }]} selected={new Set()} onSelect={vi.fn()} onInspect={onInspect} onNavigate={onNavigate} isMobile thumbnailMap={{}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Assets' }));

    expect(onNavigate).toHaveBeenCalledWith('Assets');
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('selects a directory before mobile navigation in selection mode', () => {
    const onSelect = vi.fn();
    const onNavigate = vi.fn();
    render(<ProjectGrid items={[{ name: 'Assets', path: 'Assets', type: 'dir', extension: '', category: 'other' }]} selected={new Set()} onSelect={onSelect} onNavigate={onNavigate} isMobile selectionMode thumbnailMap={{}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Assets' }));

    expect(onSelect).toHaveBeenCalledWith('Assets');
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('inspects a file immediately on mobile single click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectGrid items={[item]} selected={new Set()} onSelect={vi.fn()} onInspect={onInspect} isMobile thumbnailMap={{}} />);

    fireEvent.click(screen.getByRole('button', { name: 'asset.png' }));

    expect(onInspect).toHaveBeenCalledWith(item);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledTimes(1);
  });

  it('renders initial batch and shows sentinel for large collections', () => {
    const mockObserver = vi.fn().mockImplementation(() => ({
      observe: vi.fn(),
      disconnect: vi.fn(),
    }));
    vi.stubGlobal('IntersectionObserver', mockObserver);

    const largeItems = Array.from({ length: 150 }, (_, i) => ({
      name: `item-${i}.png`,
      path: `item-${i}.png`,
      type: 'file' as const,
      extension: '.png',
      category: 'image',
    }));

    render(
      <ProjectGrid
        items={largeItems}
        selected={new Set()}
        onSelect={vi.fn()}
        thumbnailMap={{}}
      />,
    );

    expect(screen.getByTestId('project-grid-sentinel')).toBeDefined();
    expect(screen.getByRole('button', { name: 'item-0.png' })).toBeDefined();
    expect(screen.getByRole('button', { name: 'item-79.png' })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'item-80.png' })).toBeNull();

    vi.unstubAllGlobals();
  });
});
