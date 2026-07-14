import type { ApiClient } from './client';
import type { ShareLink, ShareCreateRequest, ShareVerifyResponse, ShareInfoResponse, OkResponse } from '../types/api';

function encodeSharePath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}

export function createSharesApi(api: ApiClient) {
  return {
    create: (data: ShareCreateRequest) =>
      api.post<ShareLink>('shares', data),
    list: () => api.get<{ shares: ShareLink[] }>('shares'),
    delete: (id: string) => api.delete<OkResponse>(`shares/${id}`),
    getInfo: (id: string) => api.get<ShareInfoResponse>(`shares/${id}/info`),
    verifyPassword: (id: string, password: string) =>
      api.post<ShareVerifyResponse>(`shares/${id}/verify`, { password }),
    getDownloadUrl: (id: string, path: string) => `/api/shares/${id}/download/${encodeSharePath(path)}`,
    getPreviewUrl: (id: string, path: string) => `/api/shares/${id}/preview/${encodeSharePath(path)}`,
  };
}

export type SharesApi = ReturnType<typeof createSharesApi>;
