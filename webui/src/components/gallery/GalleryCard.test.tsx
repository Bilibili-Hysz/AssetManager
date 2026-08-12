// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GalleryEntry } from '../../types/api';

const { authMock, quotaMock, translateMock } = vi.hoisted(() => ({
  authMock: { api: { buildUrl: (path: string) => `/api/${path}` }, capabilities: { download: true } },
  quotaMock: { guardDownload: vi.fn(async () => true), refresh: vi.fn() },
  translateMock: (key: string) => key,
}));

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => authMock }));
vi.mock('../../hooks/useQuota', () => ({ useQuota: () => quotaMock }));
vi.mock('../../hooks/useI18n', () => ({ useI18n: () => ({ t: translateMock }) }));

import { GalleryCard } from './GalleryCard';

const entry: GalleryEntry = {
  name: 'hero.png', path: 'projects/hero.png', kind: 'artwork',
  parent_path: 'projects', modified: 100, thumbnail_url: '/api/thumbnails/projects/hero.png',
};

describe('GalleryCard', () => {
  beforeEach(() => {
    quotaMock.guardDownload.mockReset().mockResolvedValue(true);
    quotaMock.refresh.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders the entry name and opens on media click', () => {
    const onOpen = vi.fn();
    render(<GalleryCard entry={entry} onOpen={onOpen} />);
    expect(screen.getByText('hero.png')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'gallery.open_entry' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('shows a placeholder when the image fails to load', () => {
    render(<GalleryCard entry={entry} onOpen={() => {}} />);
    const image = screen.getByAltText('hero.png');
    fireEvent.error(image);
    expect(screen.queryByAltText('hero.png')).toBeNull();
  });

  it('toggles favorites when enabled', () => {
    const onToggleFavorite = vi.fn();
    render(<GalleryCard entry={entry} onOpen={() => {}} onToggleFavorite={onToggleFavorite} isFavorite />);
    fireEvent.click(screen.getByRole('button', { name: 'gallery.remove_favorite' }));
    expect(onToggleFavorite).toHaveBeenCalledTimes(1);
  });

  it('downloads through the quota guard and refreshes quota after', async () => {
    const openSpy = vi.fn();
    vi.stubGlobal('open', openSpy);
    render(<GalleryCard entry={entry} onOpen={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'gallery.download_entry' }));
    await vi.waitFor(() => expect(quotaMock.guardDownload).toHaveBeenCalledTimes(1));
    expect(openSpy).toHaveBeenCalledWith('/api/download/projects%2Fhero.png', '_blank', 'noopener,noreferrer');
    await vi.waitFor(() => expect(quotaMock.refresh).toHaveBeenCalledTimes(1));
  });

  it('skips the download when the quota guard denies it', async () => {
    quotaMock.guardDownload.mockResolvedValueOnce(false);
    render(<GalleryCard entry={entry} onOpen={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'gallery.download_entry' }));
    await vi.waitFor(() => expect(quotaMock.guardDownload).toHaveBeenCalledTimes(1));
    expect(quotaMock.refresh).not.toHaveBeenCalled();
  });
});
