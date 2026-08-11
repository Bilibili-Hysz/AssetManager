import type { ApiClient } from './client';
import type { ShareLink, ShareCreateRequest, ShareVerifyResponse, ShareInfoResponse, OkResponse } from '../types/api';

function encodeSharePath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}

export function createSharesApi(api: ApiClient) {
  const encodeId = (id: string) => encodeURIComponent(String(id));
  return {
    create: (data: ShareCreateRequest) =>
      api.post<ShareLink>('shares', data),
    list: () => api.get<{ shares: ShareLink[] }>('shares'),
    delete: (id: string) => api.delete<OkResponse>(`shares/${encodeId(id)}`),
    getInfo: (id: string) => api.get<ShareInfoResponse>(`shares/${encodeId(id)}/info`),
    verifyPassword: (id: string, password: string) =>
      api.post<ShareVerifyResponse>(`shares/${encodeId(id)}/verify`, { password }),
    getDownloadUrl: (id: string, path: string) =>
      api.buildUrl(`shares/${encodeId(id)}/download/${encodeSharePath(path)}`),
    getPreviewUrl: (id: string, path: string) =>
      api.buildUrl(`shares/${encodeId(id)}/preview/${encodeSharePath(path)}`),
  };
}

export type SharesApi = ReturnType<typeof createSharesApi>;
