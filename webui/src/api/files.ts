import type { ApiClient, DownloadProgress } from './client';
import type { DirectorySummariesResponse, FilesResponse } from '../types/api';

export function createFilesApi(api: ApiClient) {
  return {
    list: (params: {
      path?: string;
      sort?: string;
      order?: string;
      filter?: string;
      search?: string;
      summaries?: string;
    }, signal?: AbortSignal) => api.get<FilesResponse>('files', params as Record<string, string | undefined>, signal),

    summaries: (parent_path: string, paths: string[], signal?: AbortSignal) =>
      api.post<DirectorySummariesResponse>('files/summaries', { parent_path, paths }, signal),

    download: async (path: string, signal?: AbortSignal) => {
      // Blob download with error classification: HTTP failures surface as
      // ApiError (401/403/429/503) instead of a new tab showing JSON.
      const encoded = encodeURIComponent(path);
      const { blob, filename } = await api.getBlobWithMetadata(
        `download/${encoded}`,
        undefined,
        signal,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || path.split('/').pop() || 'download';
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Delay the revoke: Firefox grabs the blob URL from the download engine
      // asynchronously, and revoking too early can abort the save dialog.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },

    batchDownload: async (paths: string[], onProgress?: (progress: DownloadProgress) => void, signal?: AbortSignal) => {
      const progress = onProgress ?? (() => {});
      const blob = signal === undefined
        ? await api.postBlobWithProgress('download/batch', { paths }, progress)
        : await api.postBlobWithProgress('download/batch', { paths }, progress, signal);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'assets.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Delay the revoke: Firefox grabs the blob URL from the download engine
      // asynchronously, and revoking too early can abort the save dialog.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  };
}

export type FilesApi = ReturnType<typeof createFilesApi>;
