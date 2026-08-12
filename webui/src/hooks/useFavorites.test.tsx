// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GalleryEntry, SessionPrincipal } from '../types/api';
import { useFavorites } from './useFavorites';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
  showToast: vi.fn(),
  translate: (key: string) => key,
  invalidationCallback: null as ((event: unknown) => void) | null,
  invalidationDomains: [] as string[],
  auth: null as {
    api: object;
    serverInfo: { asset_root_id?: string; library_root: string; share_name: string } | null;
    principal: SessionPrincipal;
    identityGeneration: number;
  } | null,
}));

vi.mock('../api/favorites', () => ({
  createFavoritesApi: () => ({
    list: mocks.list,
    add: mocks.add,
    remove: mocks.remove,
  }),
}));

vi.mock('./useAuth', () => ({
  useAuth: () => mocks.auth,
}));

vi.mock('../components/ui/Toast', () => ({
  useToast: () => ({ showToast: mocks.showToast }),
}));

vi.mock('./useI18n', () => ({
  useI18n: () => ({ t: mocks.translate }),
}));

vi.mock('./useInvalidation', () => ({
  useInvalidation: (domains: readonly string[], callback: (event: unknown) => void) => {
    mocks.invalidationDomains = [...domains];
    mocks.invalidationCallback = callback;
  },
}));

const alice: SessionPrincipal = {
  kind: 'user',
  authenticated: true,
  role: 'user',
  display_name: 'alice',
  capabilities: {
    browse: true, preview: true, download: true, upload: false,
    manage_links: false, manage_users: false, settings: false, realtime: true,
  },
  user_profile: { id: 7, username: 'alice', role: 'user', active: true, created_at: 0 },
};

const bob: SessionPrincipal = {
  ...alice,
  display_name: 'bob',
  user_profile: { ...alice.user_profile!, id: 8, username: 'bob' },
};

const collection: GalleryEntry = {
  name: 'Collection',
  path: 'collection',
  kind: 'collection',
  parent_path: '', // "" marks a library-root entry (see types/api.ts GalleryEntry)
  modified: 1,
  child_count: 0,
  artwork_count: 1,
};

function resetAuth(principal: SessionPrincipal = alice) {
  mocks.auth = {
    api: {},
    serverInfo: {
      asset_root_id: 'library-root-id',
      library_root: 'D:/Libraries/assets',
      share_name: 'Assets',
    },
    principal,
    identityGeneration: 0,
  };
}

describe('useFavorites', () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.list.mockReset().mockResolvedValue({ favorites: [] });
    mocks.add.mockReset().mockResolvedValue({ ok: true, path: 'collection', favorite: true, changed: true });
    mocks.remove.mockReset().mockResolvedValue({ ok: true, path: 'collection', favorite: false, changed: true });
    mocks.showToast.mockReset();
    mocks.invalidationCallback = null;
    mocks.invalidationDomains = [];
    resetAuth();
  });

  it('loads GalleryEntry projections and scopes the cache by library and principal', async () => {
    mocks.list.mockResolvedValue({ favorites: [collection] });
    const { result } = renderHook(() => useFavorites());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual([collection]);
    expect(result.current.isFavorite('collection')).toBe(true);
    expect(mocks.list).toHaveBeenCalledWith();  // shared in-flight request, no per-instance signal
    const storageKey = localStorage.key(0);
    expect(storageKey).toBeTruthy();
    expect(decodeURIComponent(storageKey!)).toContain('library-root-id');
    expect(decodeURIComponent(storageKey!)).toContain('D:/Libraries/assets');
    expect(decodeURIComponent(storageKey!)).toContain('user:7');
  });

  it('optimistically updates a mutation and rolls it back with a localized toast on failure', async () => {
    let rejectAdd!: (error: Error) => void;
    mocks.add.mockImplementation(() => new Promise((_resolve, reject) => { rejectAdd = reject; }));
    const { result } = renderHook(() => useFavorites());

    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    act(() => { void result.current.addFavorite('collection'); });
    expect(result.current.isFavorite('collection')).toBe(true);
    await waitFor(() => expect(mocks.add).toHaveBeenCalledWith('collection', expect.any(AbortSignal)));

    await act(async () => {
      rejectAdd(new Error('server rejected favorite'));
    });
    await waitFor(() => expect(result.current.isFavorite('collection')).toBe(false));
    expect(mocks.showToast).toHaveBeenCalledWith('gallery.favorite_save_failed', 'error');
  });

  it('serializes rapid toggles and refreshes after the final mutation', async () => {
    let resolveAdd!: (value: unknown) => void;
    mocks.add.mockImplementation(() => new Promise(resolve => { resolveAdd = resolve; }));
    const { result } = renderHook(() => useFavorites());

    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    act(() => {
      void result.current.addFavorite('collection');
      void result.current.removeFavorite('collection');
    });
    await waitFor(() => expect(mocks.add).toHaveBeenCalledTimes(1));
    expect(mocks.remove).not.toHaveBeenCalled();

    await act(async () => { resolveAdd({ ok: true }); });
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mocks.list.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(result.current.isFavorite('collection')).toBe(false);
  });

  it('refreshes on the favorites realtime projection domain', async () => {
    const { result } = renderHook(() => useFavorites());

    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(1));
    expect(mocks.invalidationDomains).toEqual(['favorites']);
    expect(mocks.invalidationCallback).toBeTypeOf('function');

    act(() => { mocks.invalidationCallback?.(null); });
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it('clears prior identity data and does not leak favorites between users', async () => {
    mocks.list.mockResolvedValueOnce({ favorites: [collection] }).mockResolvedValueOnce({ favorites: [] });
    const { result, rerender } = renderHook(() => useFavorites());

    await waitFor(() => expect(result.current.isFavorite('collection')).toBe(true));
    mocks.auth = { ...mocks.auth!, principal: bob, identityGeneration: 1 };
    rerender();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual([]);
    expect(result.current.isFavorite('collection')).toBe(false);
    expect(mocks.list).toHaveBeenCalledTimes(2);
  });
});
