import type { ApiClient } from './client';
import type { QuotaInfo, ServerInfo, StatsResponse } from '../types/api';

export function createSystemApi(api: ApiClient) {
  return {
    getInfo: () => api.get<ServerInfo>('info'),
    getStats: () => api.get<StatsResponse>('stats'),
    getQuota: () => api.get<QuotaInfo>('quota'),
    getTunnelStatus: () => api.get<{ active: boolean; public_url: string | null }>('tunnel/status'),
  };
}

export type SystemApi = ReturnType<typeof createSystemApi>;
