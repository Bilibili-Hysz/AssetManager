import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createQuickSearchApi } from './quicksearch';

describe('quick search API contract', () => {
  it('uses the dedicated mixed file/directory endpoint with a bounded default limit', () => {
    const get = vi.fn();
    const api = createQuickSearchApi({ get } as unknown as ApiClient);
    api.search('hero');
    expect(get).toHaveBeenCalledWith('quicksearch', { q: 'hero', limit: 20 }, undefined);
  });
});