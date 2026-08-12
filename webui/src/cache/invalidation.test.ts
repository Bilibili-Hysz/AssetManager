import { describe, expect, it } from 'vitest';
import { pathRelated, shouldInvalidate } from './invalidation';

describe('invalidation matching', () => {
  it('pathRelated matches equality and either-direction prefixes', () => {
    expect(pathRelated('a/b', 'a/b')).toBe(true);
    expect(pathRelated('a/b', 'a/b/c.png')).toBe(true);
    expect(pathRelated('a/b/c.png', 'a/b')).toBe(true);
    expect(pathRelated('a/b', 'a/bc')).toBe(false);
  });

  it('null events invalidate everything', () => {
    expect(shouldInvalidate(null, ['files'], undefined)).toBe(true);
  });

  it('non-intersecting domains do not invalidate', () => {
    const event = { type: 'projection_invalidated' as const, domains: ['tags' as const], paths: [], epoch: 'e', revision: 1 };
    expect(shouldInvalidate(event, ['files'], undefined)).toBe(false);
  });

  it('intersecting domains with empty paths invalidate', () => {
    const event = { type: 'projection_invalidated' as const, domains: ['files' as const], paths: [], epoch: 'e', revision: 1 };
    expect(shouldInvalidate(event, ['files'], undefined)).toBe(true);
  });

  it('path-carrying events respect the path filter', () => {
    const event = { type: 'projection_invalidated' as const, domains: ['files' as const], paths: ['a/b/c.png'], epoch: 'e', revision: 1 };
    expect(shouldInvalidate(event, ['files'], paths => paths.some(p => pathRelated('a/b', p)))).toBe(true);
    expect(shouldInvalidate(event, ['files'], paths => paths.some(p => pathRelated('x/y', p)))).toBe(false);
  });
});
