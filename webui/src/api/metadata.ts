import type { ApiClient } from './client';
import type { ProjectDetail, Metadata, SearchResponse, TreeResponse, HomeData } from '../types/api';

export function createMetadataApi(api: ApiClient) {
  return {
    getProjectDetail: (path: string, signal?: AbortSignal) =>
      api.get<ProjectDetail>(`projects/${encodeURIComponent(path)}`, undefined, signal),
    getMeta: (path: string, signal?: AbortSignal) =>
      api.get<Metadata>(`meta/${encodeURIComponent(path)}`, undefined, signal),
    // includeStatus opts into the truncation/degradation contract: the backend
    // then returns status/sources/dropped_count/fallback_used so callers can
    // surface partial results instead of silently showing a truncated list.
    search: (q: string, tags?: string, category?: string, signal?: AbortSignal, includeStatus = true) =>
      api.get<SearchResponse>(
        'search',
        { q, tags, category, include_status: includeStatus ? 1 : undefined },
        signal,
      ),
    getTree: () => api.get<TreeResponse>('tree'),
    getHome: (signal?: AbortSignal) => api.get<HomeData>('home', undefined, signal),
  };
}

export type MetadataApi = ReturnType<typeof createMetadataApi>;
