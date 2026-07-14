import type { ApiClient } from './client';
import type { FilesResponse } from '../types/api';

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

    download: (path: string) => {
      const encoded = encodeURIComponent(path);
      window.open(`/api/download/${encoded}`, '_blank');
    },

    batchDownload: async (paths: string[]) => {
      const blob = await api.postBlob('download/batch', { paths });
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
