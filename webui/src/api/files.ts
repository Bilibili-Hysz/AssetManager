import type { ApiClient, BlobDownload, DownloadProgress } from './client';
import type { DirectorySummariesResponse, FilesResponse } from '../types/api';

export function createFilesApi(api: ApiClient) {
  return {
    list: (params: {
      path?: string;
      sort?: string;
      order?: string;
      filter?: string;
      search?: string;
      /** Serialized as 'true'/'false' by the client; backend defaults to true. */
      summaries?: boolean;
      /** Page size (1-1000); omitted = backend full listing (backward compat). */
      limit?: number;
      /** Slice start into the sorted, filtered listing; backend default 0. */
      offset?: number;
    }, signal?: AbortSignal) => api.get<FilesResponse>('files', params as Record<string, string | number | boolean | undefined>, signal),

    summaries: (parent_path: string, paths: string[], signal?: AbortSignal) =>
      api.post<DirectorySummariesResponse>('files/summaries', { parent_path, paths }, signal),

    /** Fetch a single file for download; the caller triggers the save dialog. */
    download: (path: string, signal?: AbortSignal): Promise<BlobDownload> => {
      // Blob download with error classification: HTTP failures surface as
      // ApiError (401/403/429/503) instead of a new tab showing JSON.
      const encoded = encodeURIComponent(path);
      return api.getBlobWithMetadata(
        `download/${encoded}`,
        undefined,
        signal,
      );
    },

    /** Fetch a zipped selection; the caller triggers the save dialog. */
    batchDownload: (
      paths: string[],
      onProgress?: (progress: DownloadProgress) => void,
      signal?: AbortSignal,
    ): Promise<Blob> => {
      const progress = onProgress ?? (() => {});
      return signal === undefined
        ? api.postBlobWithProgress('download/batch', { paths }, progress)
        : api.postBlobWithProgress('download/batch', { paths }, progress, signal);
    },
  };
}

export type FilesApi = ReturnType<typeof createFilesApi>;
