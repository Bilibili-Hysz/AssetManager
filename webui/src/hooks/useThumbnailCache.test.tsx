// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useThumbnailCache } from './useThumbnailCache';

const batch = vi.fn(() => Promise.resolve({ thumbnails: { 'cover.jpg': 'encoded' } }));
const api = {};
const authState = { api, identityGeneration: 0, thumbnailCacheNamespace: 'server-a|library-a|user-a' };

vi.mock('./useAuth', () => ({
  useAuth: () => authState,
}));

vi.mock('../api/thumbnails', () => ({
  createThumbnailsApi: () => ({ batch }),
}));

describe('useThumbnailCache', () => {
  afterEach(() => {
    batch.mockClear();
    sessionStorage.clear();
    authState.identityGeneration = 0;
    authState.thumbnailCacheNamespace = 'server-a|library-a|user-a';
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

  it('clears identity-scoped thumbnails after logout or user switch', async () => {
    const { result, rerender } = renderHook(() => useThumbnailCache());
    await act(async () => { await result.current.loadThumbnails(['cover.jpg']); });
    await waitFor(() => expect(result.current.getThumbnail('cover.jpg')).toBe('encoded'));

    authState.identityGeneration = 1;
    rerender();

    await waitFor(() => expect(result.current.getThumbnail('cover.jpg')).toBeUndefined());
  });

  it('removes the persisted thumbnail cache when identity changes', async () => {
    const { result, rerender } = renderHook(() => useThumbnailCache());

    act(() => {
      sessionStorage.setItem('lan_thumb_cache', JSON.stringify({ 'private.jpg': 'private-encoded' }));
      authState.identityGeneration = 1;
      rerender();
    });

    await waitFor(() => expect(sessionStorage.getItem('lan_thumb_cache')).toBeNull());
    expect(result.current.getThumbnail('private.jpg')).toBeUndefined();
  });

  it('isolates persisted thumbnails by namespace', async () => {
    sessionStorage.setItem(
      'lan_thumb_cache:server-a%7Clibrary-a%7Cuser-a',
      JSON.stringify({ 'cover.jpg': 'server-a' }),
    );
    sessionStorage.setItem(
      'lan_thumb_cache:server-b%7Clibrary-a%7Cuser-a',
      JSON.stringify({ 'cover.jpg': 'server-b' }),
    );
    const { result, rerender } = renderHook(() => useThumbnailCache());
    await waitFor(() => expect(result.current.getThumbnail('cover.jpg')).toBe('server-a'));

    authState.thumbnailCacheNamespace = 'server-b|library-a|user-a';
    rerender();
    await waitFor(() => expect(result.current.getThumbnail('cover.jpg')).toBe('server-b'));
  });

  it('does not commit a thumbnail response from a previous namespace', async () => {
    let resolveBatch!: (value: { thumbnails: { 'cover.jpg': string } }) => void;
    batch.mockReturnValueOnce(new Promise(resolve => { resolveBatch = resolve; }));
    const { result, rerender } = renderHook(() => useThumbnailCache());

    const staleRequest = result.current.loadThumbnails(['cover.jpg']);
    authState.identityGeneration = 1;
    rerender();

    await act(async () => {
      resolveBatch({ thumbnails: { 'cover.jpg': 'stale-encoded' } });
      await staleRequest;
    });

    expect(result.current.getThumbnail('cover.jpg')).toBeUndefined();
  });
});
