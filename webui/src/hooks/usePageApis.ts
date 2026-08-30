/**
 * Page-facing API factory hooks (S2 single entry).
 *
 * Pages are not allowed to import api/* factories directly (enforced by
 * scripts/check_frontend_data_fetch.py). They obtain their typed API bundles
 * through these hooks, which resolve the session client from AuthContext and
 * memoize the factories against the client identity.
 *
 * Data reads that benefit from the shared cache should still go through
 * useCachedQuery (see hooks/useProjects.ts); these hooks are
 * for mutations and for page-level flows that need an explicit API handle.
 */
import { useMemo } from 'react';
import { useAuth } from './useAuth';
import { createApiClient } from '../api/client';
import { createFilesApi } from '../api/files';
import { createGalleryApi } from '../api/gallery';
import { createMetadataApi } from '../api/metadata';
import { createNotesApi } from '../api/notes';
import { createQuickSearchApi } from '../api/quicksearch';
import { createSharesApi } from '../api/shares';
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
