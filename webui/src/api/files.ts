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

    download: (path: string) => {
      const encoded = encodeURIComponent(path);
      window.open(`/api/download/${encoded}`, '_blank');
    },

    batchDownload: async (paths: string[], onProgress?: (progress: DownloadProgress) => void) => {
      const blob = await api.postBlobWithProgress('download/batch', { paths }, onProgress ?? (() => {}));
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'assets.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    },
  };
}

export type FilesApi = ReturnType<typeof createFilesApi>;
