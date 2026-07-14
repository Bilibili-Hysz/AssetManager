import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, ChevronDown, Folder, FileText, Search } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useI18n } from '../../hooks/useI18n';
import { createMetadataApi } from '../../api/metadata';
import type { TreeItem } from '../../types/api';

interface SidebarProps {
  onNavigate: (path: string) => void;
  currentPath: string;
}

function TreeNode({ node, depth, onNavigate, onNavigateDetail, currentPath, filter }: {
  node: TreeItem;
  depth: number;
  onNavigate: (path: string) => void;
  onNavigateDetail: (path: string) => void;
  currentPath: string;
  filter: string;
}) {
  const isLeaf = node.is_leaf === true;
  const hasChildren = !!node.children?.length;
  const [expanded, setExpanded] = useState(depth < 1 || currentPath.startsWith(node.path));
  const isActive = currentPath === node.path;

  // Auto-expand when filtering
  useEffect(() => {
    if (filter) setExpanded(true);
  }, [filter]);

  // Filter check
  if (filter && !node.name.toLowerCase().includes(filter.toLowerCase())) {
    const hasMatchingChild = node.children?.some(c => c.name.toLowerCase().includes(filter.toLowerCase()));
    if (!hasMatchingChild) return null;
  }

  const handleClick = () => {
    if (isLeaf) onNavigateDetail(node.path);
    else onNavigate(node.path);
  };

  return (
    <div>
      <button
        className={`w-full flex items-center gap-1.5 px-2 py-1.5 text-sm rounded-md transition-colors text-left
          ${isActive
            ? 'bg-indigo-500/10 text-indigo-300'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={handleClick}
      >
        {/* Arrow */}
        {hasChildren ? (
          <span
            onClick={e => { e.stopPropagation(); setExpanded(!expanded); }}
            className="flex-shrink-0 w-4 h-4 flex items-center justify-center text-slate-500 hover:text-slate-300"
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}
        {/* Icon */}
        <span className="flex-shrink-0">
          {isLeaf
            ? <FileText size={14} className="text-indigo-400" />
            : <Folder size={14} className="text-amber-400" />
          }
        </span>
        {/* Name */}
        <span className="truncate flex-1 text-xs">{node.name}</span>
      </button>
      {/* Children */}
      {hasChildren && expanded && (
        <div>
          {node.children!.map(child => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onNavigate={onNavigate}
              onNavigateDetail={onNavigateDetail}
              currentPath={currentPath}
              filter={filter}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar({ onNavigate, currentPath }: SidebarProps) {
  const [tree, setTree] = useState<TreeItem[]>([]);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const { api } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const metaApi = createMetadataApi(api);

  const handleNavigateDetail = useCallback((path: string) => {
    navigate(`/detail?path=${encodeURIComponent(path)}`);
  }, [navigate]);

  useEffect(() => {
    setLoading(true);
    metaApi.getTree()
      .then(res => setTree(res.tree ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [metaApi]);

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="p-2 border-b border-slate-700/50">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder={t('sidebar.search')}
            className="w-full pl-8 pr-2 py-1.5 bg-slate-800 border border-slate-700/50 rounded-md text-xs
              text-slate-300 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 transition-colors"
          />
        </div>
      </div>
      {/* Tree */}
      <div className="flex-1 overflow-auto py-1">
        {loading ? (
          <div className="space-y-1.5 p-2">
            {[1,2,3,4,5].map(i => (
              <div key={i} className="h-6 bg-slate-800/50 rounded-md animate-pulse" />
            ))}
          </div>
        ) : tree.length === 0 ? (
          <p className="text-xs text-slate-500 text-center mt-4">{t('sidebar.no_results')}</p>
        ) : (
          tree.map(node => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              onNavigate={onNavigate}
              onNavigateDetail={handleNavigateDetail}
              currentPath={currentPath}
              filter={filter}
            />
          ))
        )}
      </div>
    </div>
  );
}