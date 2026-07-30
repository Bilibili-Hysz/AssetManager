// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectCard } from './ProjectCard';
import { SINGLE_CLICK_DELAY_MS } from './ProjectCard';

const item = {
  name: 'asset.png',
  path: 'asset.png',
  type: 'file' as const,
  size: 42,
  size_fmt: '42 B',
  modified: 1,
  extension: '.png',
  category: 'image',
};

describe('ProjectCard', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('uses Space for selection and Enter for details without conflating the actions', () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    const onOpen = vi.fn();
    const onContextMenu = vi.fn();
    render(<ProjectCard item={item} onSelect={onSelect} onInspect={onInspect} onOpen={onOpen} onContextMenu={onContextMenu} />);

    const asset = screen.getByRole('button', { name: 'asset.png, 42 B' });
    fireEvent.keyDown(asset, { key: ' ' });
    fireEvent.keyUp(asset, { key: ' ' });
    fireEvent.click(asset);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();

    fireEvent.keyDown(asset, { key: 'Enter' });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Actions for asset.png' })).not.toBe(asset);
  });

  it('cancels a pending inspect when Enter opens the card', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onOpen = vi.fn();
    render(<ProjectCard item={item} onInspect={onInspect} onOpen={onOpen} />);

    const asset = screen.getByRole('button', { name: 'asset.png, 42 B' });
    fireEvent.click(asset);
    fireEvent.keyDown(asset, { key: 'Enter' });
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('selects for ZIP download from its explicit control without inspecting the card', () => {
    const onSelect = vi.fn();
    const onOpen = vi.fn();
    render(<ProjectCard item={item} onSelect={onSelect} onOpen={onOpen} />);

    const zipSelect = screen.getByRole('button', { name: 'Select asset.png for ZIP download' });
    expect(zipSelect.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(zipSelect);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('selects the path on Enter in selection mode instead of opening', () => {
    const onSelect = vi.fn();
    const onOpen = vi.fn();
    render(<ProjectCard item={item} onSelect={onSelect} onOpen={onOpen} selectionMode />);

    fireEvent.keyDown(screen.getByRole('button', { name: 'asset.png, 42 B' }), { key: 'Enter' });

    expect(onSelect).toHaveBeenCalledWith('asset.png');
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('inspects a file immediately on mobile single click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    render(<ProjectCard item={item} onInspect={onInspect} isMobile />);

    fireEvent.click(screen.getByRole('button', { name: 'asset.png, 42 B' }));

    expect(onInspect).toHaveBeenCalledWith(item);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledTimes(1);
  });

  it('renders a directory thumbnail through the layered preview', () => {
    const { container } = render(
      <ProjectCard
        item={{ name: 'Assets', path: 'Assets', type: 'dir', extension: '', category: 'other' }}
        thumbnail="/api/thumbnails/Assets/cover.png"
      />,
    );

    expect(container.querySelector('img')?.getAttribute('src')).toBe('/api/thumbnails/Assets/cover.png');
  });

  it('opens on double click while preserving the card callback contract', () => {
    const onSelect = vi.fn();
    const onOpen = vi.fn();
    render(<ProjectCard item={item} onSelect={onSelect} onOpen={onOpen} />);

    const asset = screen.getByRole('button', { name: 'asset.png, 42 B' });
    fireEvent.doubleClick(asset);

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('does not inspect before a delayed browser double click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onOpen = vi.fn();
    render(<ProjectCard item={item} onSelect={onInspect} onOpen={onOpen} />);

    const asset = screen.getByRole('button', { name: 'asset.png, 42 B' });
    fireEvent.click(asset);
    vi.advanceTimersByTime(250);
    fireEvent.doubleClick(asset);

    expect(onInspect).not.toHaveBeenCalled();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('labels the copy link icon-only button with the asset name', () => {
    render(<ProjectCard item={item} onCopyLink={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Copy link for asset.png' })).toBeDefined();
  });
});
