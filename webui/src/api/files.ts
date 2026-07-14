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
    }) => api.get<FilesResponse>('files', params as Record<string, string | undefined>),

    download: (path: string) => {
      const encoded = encodeURIComponent(path);
      window.open(`/api/download/${encoded}`, '_blank');
    },

    batchDownload: (paths: string[]) => {
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/api/download/batch';
      form.target = '_blank';
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'paths';
      input.value = JSON.stringify(paths);
      form.appendChild(input);
      document.body.appendChild(form);
      form.submit();
      form.remove();
    },
  };
}

export type FilesApi = ReturnType<typeof createFilesApi>;