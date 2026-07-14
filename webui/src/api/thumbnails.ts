import type { ApiClient } from './client';
import type { ThumbnailBatchResponse } from '../types/api';

export function createThumbnailsApi(api: ApiClient) {
  return {
    batch: (paths: string[], size = 512) =>
      api.post<ThumbnailBatchResponse>('thumbnails/batch', { paths, size }),
  };
}

export type ThumbnailsApi = ReturnType<typeof createThumbnailsApi>;