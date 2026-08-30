import type { ApiClient } from './client';
import type {
  Collection,
  CollectionEvaluateResponse,
  CollectionMembersResponse,
  CollectionsResponse,
  OkResponse,
} from '../types/api';

export type CollectionQueryPatch = Record<string, unknown>;

export function createCollectionsApi(api: ApiClient) {
  return {
    list: () => api.get<CollectionsResponse>('collections'),
    create: (name: string, kind: 'manual' | 'smart' = 'manual', query: CollectionQueryPatch = {}) =>
      api.post<{ collection: Collection }>(
        'collections',
        kind === 'smart' ? { name, kind, query } : { name, kind },
      ),
    update: (id: number, patch: { name?: string; query?: CollectionQueryPatch }) =>
      api.patch<OkResponse>(`collections/${id}`, patch),
    delete: (id: number) => api.delete<OkResponse>(`collections/${id}`),
    members: (id: number) =>
      api.get<CollectionMembersResponse>(`collections/${id}/members`),
    addMembers: (id: number, paths: string[]) =>
      api.post<{ added: number }>(`collections/${id}/members`, { paths }),
    removeMembers: (id: number, paths: string[]) =>
      api.deleteWithBody<{ removed: number }>(`collections/${id}/members`, { paths }),
    evaluate: (id: number, limit = 200, offset = 0) =>
      api.get<CollectionEvaluateResponse>(
        `collections/${id}/evaluate?limit=${limit}&offset=${offset}`,
      ),
  };
}

export type CollectionsApi = ReturnType<typeof createCollectionsApi>;
