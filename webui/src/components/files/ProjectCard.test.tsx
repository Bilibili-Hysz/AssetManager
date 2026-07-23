// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectCard } from './ProjectCard';

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
  afterEach(cleanup);

  it('uses Space for selection and Enter for details without conflating the actions', () => {
    const onSelect = vi.fn();
    const onOpen = vi.fn();
    const onContextMenu = vi.fn();
    render(<ProjectCard item={item} onSelect={onSelect} onOpen={onOpen} onContextMenu={onContextMenu} />);

    const asset = screen.getByRole('button', { name: 'asset.png, 42 B' });
    fireEvent.keyDown(asset, { key: ' ' });
    fireEvent.keyUp(asset, { key: ' ' });
    fireEvent.click(asset);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();

    fireEvent.keyDown(asset, { key: 'Enter' });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Actions for asset.png' })).not.toBe(asset);
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
});
