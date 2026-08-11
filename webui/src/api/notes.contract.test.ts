import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createNotesApi } from './notes';

function setup() {
  const put = vi.fn();
  const client = { put } as unknown as ApiClient;
  return { api: createNotesApi(client), put };
}

describe('notes API contract', () => {
  it('PUTs encoded paths and note text', () => {
    const { api, put } = setup();
    api.save('projects/报告 2.pdf', 'hello\nworld');
    expect(put).toHaveBeenCalledWith('notes/projects%2F%E6%8A%A5%E5%91%8A%202.pdf', { notes: 'hello\nworld' });
  });
});
