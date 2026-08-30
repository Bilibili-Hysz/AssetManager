import { describe, expect, it } from 'vitest';
import { buildCollectionSnapshot } from './collectionSnapshot';

describe('buildCollectionSnapshot', () => {
  it('returns null when no filter surface is active', () => {
    expect(buildCollectionSnapshot({})).toBeNull();
    expect(buildCollectionSnapshot({ q: '', tag: null })).toBeNull();
    expect(buildCollectionSnapshot({ q: '   ' })).toBeNull();
  });

  it('maps the header search q onto the fts dimension', () => {
    expect(buildCollectionSnapshot({ q: 'white cat', tag: null })).toEqual({
      fts: 'white cat',
    });
  });

  it('maps the active tag onto the tags dimension with tag_match all', () => {
    expect(buildCollectionSnapshot({ q: null, tag: 'featured' })).toEqual({
      tags: ['featured'],
      tag_match: 'all',
    });
  });

  it('combines q and tag into one predicate', () => {
    expect(buildCollectionSnapshot({ q: 'hero', tag: 'featured' })).toEqual({
      fts: 'hero',
      tags: ['featured'],
      tag_match: 'all',
    });
  });

  it('trims the q before serializing', () => {
    expect(buildCollectionSnapshot({ q: '  hero  ' })).toEqual({ fts: 'hero' });
  });
});
