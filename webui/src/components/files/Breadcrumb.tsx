import { ChevronRight, Home } from 'lucide-react';

interface BreadcrumbProps {
  path: string;
  onNavigate: (path: string) => void;
}

export function Breadcrumb({ path, onNavigate }: BreadcrumbProps) {
  const parts = path ? path.split('/').filter(Boolean) : [];

  return (
    <div className="flex items-center gap-1 px-4 py-2 border-b border-slate-700/50 bg-slate-900/30 text-xs text-slate-400 flex-shrink-0">
      <button
        onClick={() => onNavigate('')}
        className="flex items-center gap-1 hover:text-slate-200 transition-colors p-0.5"
      >
        <Home size={13} />
      </button>
      {parts.length > 0 && <ChevronRight size={12} className="text-slate-600" />}
      {parts.map((part, i) => {
        const fullPath = parts.slice(0, i + 1).join('/');
        const isLast = i === parts.length - 1;
        return (
          <span key={fullPath} className="flex items-center gap-1">
            <button
              onClick={() => onNavigate(fullPath)}
              className={`hover:text-slate-200 transition-colors px-0.5 ${isLast ? 'text-slate-200 font-medium' : ''}`}
            >
              {part}
            </button>
            {!isLast && <ChevronRight size={12} className="text-slate-600" />}
          </span>
        );
      })}
    </div>
  );
}