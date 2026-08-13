import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, FileText, Folder, Search, Star, Tag as TagIcon, X } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useI18n } from '../../hooks/useI18n';
import { useFavorites } from '../../hooks/useFavorites';
import { createMetadataApi } from '../../api/metadata';
import { createTagsApi } from '../../api/tags';
import { useInvalidation } from '../../hooks/useInvalidation';
import type { Tag, TreeItem } from '../../types/api';

interface SidebarProps {
  onNavigate: (path: string) => void;
  currentPath: string;
  activeTag?: string | null;
  onTagFilter?: (tag: string) => void;
  onClearTagFilter?: () => void;
  tagsRefreshKey?: number;
}

const matchesFilter = (node: TreeItem, filter: string): boolean =>
  !filter || node.name.toLowerCase().includes(filter.toLowerCase()) || node.children?.some(child => matchesFilter(child, filter)) === true;

function collectExpandablePaths(nodes: TreeItem[]): Set<string> {
  const paths = new Set<string>();
  for (const node of nodes) {
    if (node.children?.length) {
      paths.add(node.path);
      for (const path of collectExpandablePaths(node.children)) paths.add(path);
    }
  }
  return paths;
}

function collectActiveAncestors(nodes: TreeItem[], currentPath: string): Set<string> {
  const paths = new Set<string>();
  if (!currentPath) return paths;
  for (const node of nodes) {
    if (node.children?.length && (currentPath === node.path || currentPath.startsWith(`${node.path}/`))) {
      paths.add(node.path);
      for (const path of collectActiveAncestors(node.children, currentPath)) paths.add(path);
    }
  }
  return paths;
}

function parentPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.slice(0, -1).join('/');
}

function workspaceDetailUrl(path: string): string {
  return `/detail?path=${encodeURIComponent(path)}&from=workspace&context=${encodeURIComponent(parentPath(path))}`;
}

function TreeNode({ node, depth, expandedPaths, onToggle, onNavigate, onNavigateDetail, currentPath, filter }: {
  node: TreeItem;
  depth: number;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  onNavigate: (path: string) => void;
  onNavigateDetail: (path: string) => void;
  currentPath: string;
  filter: string;
}) {
  const isLeaf = node.is_leaf === true;
  const hasChildren = !!node.children?.length;
  const isFiltering = Boolean(filter);
  const expanded = expandedPaths.has(node.path) || isFiltering;
  const { t } = useI18n();
  if (!matchesFilter(node, filter)) return null;

  return (
    <div>
      <div className="relative min-h-8">
        <button
          type="button"
          data-testid={`tree-node-row-${node.path}`}
          className={`flex min-h-8 w-full min-w-0 items-center gap-1.5 px-2 text-left text-xs transition-colors ${currentPath === node.path ? 'bg-indigo-500/10 text-indigo-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}
          onClick={() => isLeaf ? onNavigateDetail(node.path) : onNavigate(node.path)}
        >
          <span aria-hidden="true" data-testid={`tree-node-indent-${node.path}`} className="flex-shrink-0" style={{ width: `${depth * 14 + 16}px` }} />
          <span className="flex-shrink-0" data-testid={`tree-node-icon-${node.path}`}>{isLeaf ? <FileText size={14} className="text-indigo-400" /> : <Folder size={14} className="text-amber-400" />}</span>
          <span className="block truncate">{node.name}</span>
        </button>
        {hasChildren && (
          <button
            type="button"
            aria-label={t(expanded ? 'sidebar.collapseNode' : 'sidebar.expandNode', node.name)}
            aria-disabled={isFiltering}
            aria-expanded={expanded}
            disabled={isFiltering}
            title={isFiltering ? t('sidebar.clearFilterToChangeExpansion') : undefined}
            onClick={event => { event.stopPropagation(); onToggle(node.path); }}
            className="absolute top-1/2 z-10 flex h-4 w-4 -translate-y-1/2 items-center justify-center text-slate-500 hover:text-slate-300"
            style={{ left: `${8 + depth * 14}px` }}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        )}
      </div>
      {hasChildren && expanded && node.children!.map(child => (
        <TreeNode key={child.path} node={child} depth={depth + 1} expandedPaths={expandedPaths}
          onToggle={onToggle} onNavigate={onNavigate} onNavigateDetail={onNavigateDetail}
          currentPath={currentPath} filter={filter} />
      ))}
    </div>
  );
}

export function Sidebar({ onNavigate, currentPath, activeTag = null, onTagFilter, onClearTagFilter, tagsRefreshKey = 0 }: SidebarProps) {
  const [tree, setTree] = useState<TreeItem[]>([]);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set());
  const [filter, setFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagsLoading, setTagsLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const { api } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const metaApi = useMemo(() => createMetadataApi(api), [api]);
  const tagsApi = useMemo(() => createTagsApi(api), [api]);
  const { items: favItems, loading: favoritesLoading } = useFavorites();
  const requestGeneration = useRef(0);
  const tagsRequestGeneration = useRef(0);
  const mounted = useRef(true);

  const refreshTree = useCallback(() => {
    if (!mounted.current) return;
    const generation = ++requestGeneration.current;
    setLoading(true);
    metaApi.getTree().then(res => {
      if (mounted.current && generation === requestGeneration.current) setTree(res.tree ?? []);
    }).catch(() => {}).finally(() => {
      if (mounted.current && generation === requestGeneration.current) setLoading(false);
    });
  }, [metaApi]);

  const refreshTags = useCallback(() => {
    if (!mounted.current) return;
    const generation = ++tagsRequestGeneration.current;
    setTagsLoading(true);
    tagsApi.list().then(res => {
      if (mounted.current && generation === tagsRequestGeneration.current) setTags(res.tags ?? []);
    }).catch(() => {
      if (mounted.current && generation === tagsRequestGeneration.current) setTags([]);
    }).finally(() => {
      if (mounted.current && generation === tagsRequestGeneration.current) setTagsLoading(false);
    });
  }, [tagsApi]);

  useEffect(() => {
    mounted.current = true;
    refreshTree();
    return () => { mounted.current = false; requestGeneration.current += 1; tagsRequestGeneration.current += 1; };
  }, [refreshTree]);

  useEffect(() => { refreshTags(); }, [refreshTags, tagsRefreshKey]);
  useInvalidation(['tree'], () => { void refreshTree(); });
  useInvalidation(['tags'], () => { void refreshTags(); });
  useEffect(() => {
    const ancestors = collectActiveAncestors(tree, currentPath);
    if (ancestors.size) setExpandedPaths(paths => new Set([...paths, ...ancestors]));
  }, [currentPath, tree]);

  const togglePath = useCallback((path: string) => setExpandedPaths(paths => {
    const next = new Set(paths);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  }), []);
  const expandAll = useCallback(() => setExpandedPaths(collectExpandablePaths(tree)), [tree]);
  const collapseAll = useCallback(() => setExpandedPaths(new Set()), []);
  const isFiltering = Boolean(filter);
  const visibleTags = useMemo(() => {
    const query = tagFilter.trim().toLocaleLowerCase();
    return tags.filter(tag => !query || tag.name.toLocaleLowerCase().includes(query));
  }, [tagFilter, tags]);

  return (
    <div className="workspace-sidebar flex h-full flex-col">
      {(favoritesLoading || favItems.length > 0) && (
        <section className="workspace-sidebar-section workspace-sidebar-favorites border-b border-slate-700 bg-slate-900 p-2" aria-labelledby="sidebar-favorites-heading">
          <div className="workspace-sidebar-section-heading mb-1.5 flex items-center gap-1.5">
            <Star size={12} className="text-amber-400" aria-hidden="true" />
            <h2 id="sidebar-favorites-heading" className="text-xs font-medium text-slate-300">{t('gallery.nav_favorites')}</h2>
            <span className="text-[10px] text-slate-500">{favItems.length}</span>
          </div>
          {favoritesLoading ? (
            <div className="h-6 animate-pulse bg-slate-800" aria-label={t('gallery.loading')} />
          ) : (
            <div className="max-h-32 space-y-0.5 overflow-y-auto">
              {favItems.slice(0, 10).map(item => (
                <button
                  key={item.path}
                  type="button"
                  aria-current={currentPath === item.path ? 'page' : undefined}
                  aria-label={t('action.open_item', item.name)}
                  className={`flex min-h-7 w-full items-center gap-1.5 rounded px-2 text-left text-xs transition-colors ${currentPath === item.path ? 'bg-indigo-500/10 text-indigo-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}
                  onClick={() => navigate(workspaceDetailUrl(item.path))}
                >
                  <FileText size={13} className="flex-shrink-0 text-indigo-400" aria-hidden="true" />
                  <span className="block truncate">{item.name}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="workspace-sidebar-section workspace-sidebar-folders border-b border-slate-700 bg-slate-900 p-2">
        <div className="workspace-sidebar-section-heading mb-2 flex items-center justify-between gap-2">
          <h2 className="text-xs font-medium text-slate-300">{t('sidebar.folders')}</h2>
          <div className="flex items-center gap-1">
            <button type="button" aria-label={t('sidebar.expandAll')} aria-disabled={isFiltering} disabled={isFiltering} title={isFiltering ? t('sidebar.clearFilterToChangeExpansion') : undefined} onClick={expandAll} className="flex h-10 w-10 items-center justify-center text-slate-400 disabled:cursor-not-allowed disabled:opacity-50"><ChevronsUpDown size={14} /></button>
            <button type="button" aria-label={t('sidebar.collapseAll')} aria-disabled={isFiltering} disabled={isFiltering} title={isFiltering ? t('sidebar.clearFilterToChangeExpansion') : undefined} onClick={collapseAll} className="flex h-10 w-10 items-center justify-center text-slate-400 disabled:cursor-not-allowed disabled:opacity-50"><ChevronsDownUp size={14} /></button>
          </div>
        </div>
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
          <input className="workspace-sidebar-search-input w-full border border-slate-700 bg-slate-800 py-1.5 pl-8 pr-2 text-xs text-slate-300" type="text" value={filter} onChange={e => setFilter(e.target.value)} aria-label={t('sidebar.search')} placeholder={t('sidebar.search')} />
        </div>
      </section>

      <div className="flex-1 overflow-auto py-1">
        {loading ? (
          <div className="space-y-1.5 p-2">{[1, 2, 3, 4, 5].map(i => <div key={i} className="h-6 animate-pulse bg-slate-800" />)}</div>
        ) : tree.length === 0 ? (
          <p className="mt-4 text-center text-xs text-slate-500">{t('sidebar.no_results')}</p>
        ) : (
          tree.map(node => <TreeNode key={node.path} node={node} depth={0} expandedPaths={expandedPaths} onToggle={togglePath} onNavigate={onNavigate} onNavigateDetail={path => navigate(workspaceDetailUrl(path))} currentPath={currentPath} filter={filter} />)
        )}
      </div>

      <section className="workspace-sidebar-section workspace-sidebar-tags flex-shrink-0 border-t border-slate-700 bg-slate-900 p-2" aria-labelledby="sidebar-tags-heading">
        <div className="workspace-sidebar-section-heading mb-2 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <TagIcon size={12} className="text-indigo-400" aria-hidden="true" />
            <h2 id="sidebar-tags-heading" className="text-xs font-medium text-slate-300">{t('info.tags')}</h2>
            <span className="text-[10px] text-slate-500">{tags.length}</span>
          </div>
          {activeTag && onClearTagFilter && <button type="button" onClick={onClearTagFilter} aria-label={t('browse.clear_tag')} title={t('browse.clear_tag')} className="rounded p-1 text-indigo-300 hover:bg-indigo-500/15"><X size={13} aria-hidden="true" /></button>}
        </div>
        {tags.length > 0 && (
          <div className="relative mb-2">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
            <input className="workspace-sidebar-search-input w-full border border-slate-700 bg-slate-800 py-1.5 pl-8 pr-2 text-xs text-slate-300" type="text" value={tagFilter} onChange={event => setTagFilter(event.target.value)} aria-label={t('info.tags')} placeholder={t('info.tags')} />
          </div>
        )}
        {tagsLoading ? (
          <div className="h-6 animate-pulse bg-slate-800" aria-label={t('gallery.loading')} />
        ) : tags.length === 0 ? (
          <p className="px-1 text-xs text-slate-500">{t('info.no_tags')}</p>
        ) : visibleTags.length === 0 ? (
          <p className="px-1 text-xs text-slate-500">{t('sidebar.no_results')}</p>
        ) : (
          <div className="workspace-tag-list max-h-36 space-y-0.5 overflow-y-auto">
            {visibleTags.map(tag => {
              const selected = activeTag === tag.name;
              return <button key={tag.name} type="button" aria-pressed={selected} onClick={() => selected ? onClearTagFilter?.() : onTagFilter?.(tag.name)} className={`workspace-tag-row flex min-h-7 w-full items-center justify-between gap-2 rounded px-2 text-left text-xs transition-colors ${selected ? 'workspace-tag-row-active bg-indigo-500/15 text-indigo-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}><span className="min-w-0 truncate">{tag.name}</span><span className={`flex-shrink-0 text-[10px] ${selected ? 'text-indigo-300' : 'text-slate-500'}`}>{tag.count}</span></button>;
            })}
          </div>
        )}
      </section>
    </div>
  );
}
