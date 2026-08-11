import type { ApiClient } from './client';

export interface SaveNotesResponse {
  ok: boolean;
  path: string;
  notes: string;
}

export function createNotesApi(api: ApiClient) {
  return {
    /** Persist (or clear, when notes is empty) the note for a path. */
    save: (path: string, notes: string) =>
      api.put<SaveNotesResponse>(`notes/${encodeURIComponent(path)}`, { notes }),
  };
}

export type NotesApi = ReturnType<typeof createNotesApi>;
