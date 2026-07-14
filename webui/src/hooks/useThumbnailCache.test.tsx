// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useThumbnailCache } from './useThumbnailCache';

const batch = vi.fn(() => Promise.resolve({ thumbnails: { 'cover.jpg': 'encoded' } }));
const api = {};

vi.mock('./useAuth', () => ({
  useAuth: () => ({ api }),
}));

vi.mock('../api/thumbnails', () => ({
  createThumbnailsApi: () => ({ batch }),
}));

describe('useThumbnailCache', () => {
  afterEach(() => {
    batch.mockClear();
    sessionStorage.clear();
  });

  it('keeps the thumbnail loader stable after cache updates', async () => {
    const { result } = renderHook(() => useThumbnailCache());
    const initialLoader = result.current.loadThumbnails;

    await act(async () => {
      await result.current.loadThumbnails(['cover.jpg']);
    });

    await waitFor(() => expect(result.current.getThumbnail('cover.jpg')).toBe('encoded'));
    expect(result.current.loadThumbnails).toBe(initialLoader);
  });
});
