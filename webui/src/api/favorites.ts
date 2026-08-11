import type { ApiClient } from './client';
import type { FavoriteMutationResponse, FavoritesResponse } from '../types/api';

export function createFavoritesApi(api: ApiClient) {
  return {
    list: (signal?: AbortSignal) =>
      api.get<FavoritesResponse>('favorites', undefined, signal),
    add: (path: string, signal?: AbortSignal) =>
      api.post<FavoriteMutationResponse>('favorites', { path }, signal),
    remove: (path: string, signal?: AbortSignal) =>
      api.post<FavoriteMutationResponse>('favorites/remove', { path }, signal),
  };
}

export type FavoritesApi = ReturnType<typeof createFavoritesApi>;
