import type { ApiClient } from './client';
import type { TagsResponse, OkResponse } from '../types/api';

export function createTagsApi(api: ApiClient) {
  return {
    list: () => api.get<TagsResponse>('tags'),
    add: (tag: string, filePath: string) =>
      api.post<OkResponse>('tags', { tag, file_path: filePath }),
    remove: (tag: string, filePath: string) =>
      api.post<OkResponse>('tags/remove', { tag, file_path: filePath }),
    rename: (oldName: string, newName: string) =>
      api.put<OkResponse>(`tags/${encodeURIComponent(oldName)}`, { new_name: newName }),
    delete: (name: string) =>
      api.delete<OkResponse>(`tags/${encodeURIComponent(name)}`),
  };
}

export type TagsApi = ReturnType<typeof createTagsApi>;