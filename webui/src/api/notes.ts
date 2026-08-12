import type { ApiClient } from './client';
import type { SaveNotesResponse } from '../types/api';

export function createNotesApi(api: ApiClient) {
  return {
    /** Persist (or clear, when notes is empty) the note for a path. */
    save: (path: string, notes: string) =>
      api.put<SaveNotesResponse>(`notes/${encodeURIComponent(path)}`, { notes }),
  };
}

export type NotesApi = ReturnType<typeof createNotesApi>;
