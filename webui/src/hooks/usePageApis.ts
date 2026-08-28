/**
 * Page-facing API factory hooks (S2 single entry).
 *
 * Pages are not allowed to import api/* factories directly (enforced by
 * scripts/check_frontend_data_fetch.py). They obtain their typed API bundles
 * through these hooks, which resolve the session client from AuthContext and
 * memoize the factories against the client identity.
 *
 * Data reads that benefit from the shared cache should still go through
 * useCachedQuery (see hooks/useCommerce.ts / useProjects.ts); these hooks are
 * for mutations and for page-level flows that need an explicit API handle.
 */
import { useMemo } from 'react';
import { useAuth } from './useAuth';
import { useSellerAuth } from '../stores/SellerAuthContext';
import { createApiClient } from '../api/client';
import { ForbiddenError, UnauthorizedError } from '../api/errors';
import { createFilesApi } from '../api/files';
import { createGalleryApi } from '../api/gallery';
import { createMetadataApi } from '../api/metadata';
import { createNotesApi } from '../api/notes';
import { createQuickSearchApi } from '../api/quicksearch';
import { createSharesApi } from '../api/shares';
import { createShopApi, type ShopApi } from '../api/shop';
import { createSystemApi } from '../api/system';
import { createTagsApi } from '../api/tags';
import { createUsersApi } from '../api/users';

export function useFilesApi() {
  const { api } = useAuth();
  return useMemo(() => createFilesApi(api), [api]);
}

export function useGalleryApi() {
  const { api } = useAuth();
  return useMemo(() => createGalleryApi(api), [api]);
}

export function useMetadataApi() {
  const { api } = useAuth();
  return useMemo(() => createMetadataApi(api), [api]);
}

export function useNotesApi() {
  const { api } = useAuth();
  return useMemo(() => createNotesApi(api), [api]);
}

export function useQuicksearchApi() {
  const { api } = useAuth();
  return useMemo(() => createQuickSearchApi(api), [api]);
}

export function useSharesApi() {
  const { api } = useAuth();
  return useMemo(() => createSharesApi(api), [api]);
}

export function useShopApi() {
  const { api } = useAuth();
  return useMemo(() => createShopApi(api), [api]);
}

/**
 * Seller-surface variant: uses the SellerAuthContext dedicated client so a
 * seller-session 401 is never interpreted as a main-session expiry.
 *
 * The seller cookie can expire independently of the main session; seller
 * endpoints then answer 401/403. Each wrapped method triggers exactly one
 * seller status re-probe (SellerAuthContext.refresh) on such failures — so the
 * provider flips to its login gate instead of pages failing with raw auth
 * errors — and rethrows the original error untouched.
 */
export function useSellerShopApi() {
  const { sellerApi, refresh } = useSellerAuth();
  return useMemo(() => wrapSellerShopApi(createShopApi(sellerApi), () => void refresh?.()), [sellerApi, refresh]);
}

function isSellerAuthFailure(error: unknown): boolean {
  return error instanceof UnauthorizedError || error instanceof ForbiddenError;
}

/** Wrap every async shop method with the one-shot auth-failure re-probe. */
function wrapSellerShopApi(shopApi: ShopApi, onAuthFailure: () => void): ShopApi {
  const wrapped: Record<string, unknown> = { ...shopApi };
  for (const [key, value] of Object.entries(shopApi)) {
    if (typeof value !== 'function') continue;
    const original = value as (...args: unknown[]) => unknown;
    wrapped[key] = (...args: unknown[]) => {
      const result = original(...args);
      // Sync members (URL builders) pass through untouched.
      if (!(result instanceof Promise)) return result;
      return result.catch((error: unknown) => {
        if (isSellerAuthFailure(error)) onAuthFailure();
        throw error;
      });
    };
  }
  return wrapped as ShopApi;
}

export function useSystemApi() {
  const { api } = useAuth();
  return useMemo(() => createSystemApi(api), [api]);
}

export function useTagsApi() {
  const { api } = useAuth();
  return useMemo(() => createTagsApi(api), [api]);
}

export function useUsersApi() {
  const { api } = useAuth();
  return useMemo(() => createUsersApi(api), [api]);
}

/**
 * Share pages are reachable before authentication and deliberately use a
 * dedicated client: a wrong share password answers 401, which must not be
 * interpreted as a session expiry by the global AuthContext client.
 */
export function usePublicShareApi() {
  return useMemo(() => {
    const api = createApiClient();
    return createSharesApi(api);
  }, []);
}
