import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createMetadataApi } from './metadata';

function setup() {
  const get = vi.fn();
  const client = { get } as unknown as ApiClient;
  return { api: createMetadataApi(client), get };
}

describe('metadata API contract', () => {
  it('getProjectDetail encodes the whole path segment-by-segment unsafe chars and forwards AbortSignal', () => {
    const { api, get } = setup();
    const signal = new AbortController().signal;
    api.getProjectDetail('projects/报告 2.pdf', signal);
    expect(get).toHaveBeenCalledWith('projects/projects%2F%E6%8A%A5%E5%91%8A%202.pdf', undefined, signal);
  });

  it('getMeta encodes the whole path and forwards AbortSignal', () => {
    const { api, get } = setup();
    const signal = new AbortController().signal;
    api.getMeta('assets/hero icon.png', signal);
    expect(get).toHaveBeenCalledWith('meta/assets%2Fhero%20icon.png', undefined, signal);
  });

  it('search sends q, tags and category as query params', () => {
    const { api, get } = setup();
    api.search('猫', 'hero', 'image');
    expect(get).toHaveBeenCalledWith('search', { q: '猫', tags: 'hero', category: 'image' }, undefined);
  });

  it('search keeps tags/category keys when omitted (client drops empties)', () => {
    const { api, get } = setup();
    api.search('猫');
    expect(get).toHaveBeenCalledWith('search', { q: '猫', tags: undefined, category: undefined }, undefined);
  });

  it('getTree gets tree without params', () => {
    const { api, get } = setup();
    api.getTree();
    expect(get).toHaveBeenCalledWith('tree');
  });

  it('getHome gets home and forwards AbortSignal and the DTO', async () => {
    const { api, get } = setup();
    const sentinel = { projects: [], recent: [] };
    get.mockResolvedValue(sentinel);
    const signal = new AbortController().signal;
    await expect(api.getHome(signal)).resolves.toBe(sentinel);
    expect(get).toHaveBeenCalledWith('home', undefined, signal);
  });
});
