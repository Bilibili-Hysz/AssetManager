import type { ApiClient } from './client';
import type {
  GalleryCollectionResponse,
  GalleryHomeResponse,
  GalleryResolveResponse,
} from '../types/api';

export function createGalleryApi(api: ApiClient) {
  return {
    home: (signal?: AbortSignal) => api.get<GalleryHomeResponse>('gallery/home', undefined, signal),
    collection: (
      path: string,
      params?: { sort?: string; kind?: string },
      signal?: AbortSignal,
    ) => api.get<GalleryCollectionResponse>('gallery/collection', { path, ...params }, signal),
    resolve: (path: string, signal?: AbortSignal) =>
      api.get<GalleryResolveResponse>('gallery/resolve', { path }, signal),
  };
}

export type GalleryApi = ReturnType<typeof createGalleryApi>;
