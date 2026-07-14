import type { ApiClient } from './client';
import type { ProjectDetail, Metadata, SearchResponse, TreeResponse, HomeData } from '../types/api';

export function createMetadataApi(api: ApiClient) {
  return {
    getProjectDetail: (path: string) =>
      api.get<ProjectDetail>(`projects/${encodeURIComponent(path)}`),
    getMeta: (path: string) =>
      api.get<Metadata>(`meta/${encodeURIComponent(path)}`),
    search: (q: string, tags?: string, category?: string) =>
      api.get<SearchResponse>('search', { q, tags, category }),
    getTree: () => api.get<TreeResponse>('tree'),
    getHome: () => api.get<HomeData>('home'),
  };
}

export type MetadataApi = ReturnType<typeof createMetadataApi>;