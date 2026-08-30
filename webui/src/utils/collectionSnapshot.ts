import type { CollectionQueryPatch } from '../api/collections';

/**
 * The BrowsePage query state that can be snapshotted into a smart
 * collection predicate. The workspace currently has two filter surfaces:
 * the header name search (`q`, served by /api/search's FTS source) and the
 * active tag filter.
 */
export interface BrowseQueryState {
  q?: string | null;
  tag?: string | null;
}

/**
 * Serialize the current browse query state into a smart-collection
 * predicate (the ``query_json`` of a ``kind: 'smart'`` collection).
 *
 * - `q` maps to the ``fts`` dimension (shared FTS syntax: bare words AND,
 *   `|` OR, `-` exclusion, quotes, `name:`/`tag:`/`notes:` fields).
 * - `tag` maps to the ``tags`` dimension with ``tag_match: 'all'`` (a
 *   single tag, so all/any behave identically — the explicit value pins
 *   the semantics for future multi-tag snapshots).
 *
 * Returns null when neither surface is active (the collection should be
 * created as a plain manual one).
 */
export function buildCollectionSnapshot(state: BrowseQueryState): CollectionQueryPatch | null {
  const query: CollectionQueryPatch = {};
  const q = state.q?.trim();
  if (q) query.fts = q;
  if (state.tag) {
    query.tags = [state.tag];
    query.tag_match = 'all';
  }
  return Object.keys(query).length > 0 ? query : null;
}
