// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectGrid } from './ProjectGrid';

describe('ProjectGrid', () => {
  afterEach(cleanup);

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
    const onZipSelect = vi.fn();
    const onInspect = vi.fn();
    render(
      <ProjectGrid
        items={[{ name: 'asset.png', path: 'asset.png', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.png', category: 'image' }]}
        selected={new Set()}
        onSelect={vi.fn()}
        onZipSelect={onZipSelect}
        onInspect={onInspect}
        thumbnailMap={{}}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Select asset.png for ZIP download' }));
    expect(onZipSelect).toHaveBeenCalledWith('asset.png');
    expect(onInspect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'asset.png, 1 B' }));
    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({ path: 'asset.png' }));
  });

  it('navigates directories without inspecting, opening details, or selecting ZIP items', () => {
    const onNavigate = vi.fn();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const onZipSelect = vi.fn();
    render(
      <ProjectGrid
        items={[{ name: 'nested', path: 'parent/nested', type: 'dir', extension: '', category: 'other' }]}
        selected={new Set()}
        onSelect={vi.fn()}
        onZipSelect={onZipSelect}
        onInspect={onInspect}
        onDoubleClick={onDoubleClick}
        onNavigate={onNavigate}
        thumbnailMap={{}}
      />,
    );

    const directory = screen.getByRole('button', { name: 'nested' });
    fireEvent.click(directory);
    fireEvent.doubleClick(directory);
    fireEvent.keyDown(directory, { key: 'Enter' });

    expect(onNavigate).toHaveBeenCalledTimes(3);
    expect(onNavigate).toHaveBeenCalledWith('parent/nested');
    expect(onInspect).not.toHaveBeenCalled();
    expect(onDoubleClick).not.toHaveBeenCalled();
    expect(onZipSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Select nested for ZIP download' })).toBeNull();
  });
});
