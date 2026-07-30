import type { ApiClient } from './client';
import type { ProjectDetail, Metadata, SearchResponse, TreeResponse, HomeData } from '../types/api';

export function createMetadataApi(api: ApiClient) {
  return {
    getProjectDetail: (path: string, signal?: AbortSignal) =>
      api.get<ProjectDetail>(`projects/${encodeURIComponent(path)}`, undefined, signal),
    getMeta: (path: string, signal?: AbortSignal) =>
      api.get<Metadata>(`meta/${encodeURIComponent(path)}`, undefined, signal),
    search: (q: string, tags?: string, category?: string, signal?: AbortSignal) =>
      api.get<SearchResponse>('search', { q, tags, category }, signal),
    getTree: () => api.get<TreeResponse>('tree'),
    getHome: (signal?: AbortSignal) => api.get<HomeData>('home', undefined, signal),
  };
}

export type MetadataApi = ReturnType<typeof createMetadataApi>;
