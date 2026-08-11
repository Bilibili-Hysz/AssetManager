import type { ApiClient } from './client';
import type { SearchResult } from '../types/api';

/** Lightweight mixed file/directory search for the global command palette. */
export function createQuickSearchApi(api: ApiClient) {
  return {
    search: (query: string, limit = 20, signal?: AbortSignal) =>
      api.get<{ results: SearchResult[] }>('quicksearch', { q: query, limit }, signal),
  };
}

export type QuickSearchApi = ReturnType<typeof createQuickSearchApi>;