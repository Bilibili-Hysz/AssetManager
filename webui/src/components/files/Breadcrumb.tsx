import { ChevronRight, Home, PanelLeft, PanelRight } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';

interface BreadcrumbProps {
  path: string;
  onNavigate: (path: string) => void;
  onSidebarToggle?: () => void;
  onInfoToggle?: () => void;
  sidebarOpen?: boolean;
  infoOpen?: boolean;
}

export function Breadcrumb({ path, onNavigate, onSidebarToggle, onInfoToggle, sidebarOpen = true, infoOpen = true }: BreadcrumbProps) {
  const { t } = useI18n();
  const parts = path ? path.split('/').filter(Boolean) : [];

  return (
    <nav aria-label="Workspace navigation" className="flex items-center gap-2 border-b border-slate-700/50 bg-slate-900/30 px-3 py-2 text-xs text-slate-400">
      {onSidebarToggle && <button
        type="button"
        onClick={onSidebarToggle}
        aria-label={t(sidebarOpen ? 'action.close_sidebar' : 'action.open_sidebar')}
        title={t(sidebarOpen ? 'action.close_sidebar' : 'action.open_sidebar')}
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
      ><PanelLeft size={16} aria-hidden="true" /></button>}
      <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
      <button
        type="button"
        onClick={() => onNavigate('')}
        className="flex items-center gap-1 hover:text-slate-200 transition-colors p-0.5"
        aria-label="Home"
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
      {onInfoToggle && <button
        type="button"
        onClick={onInfoToggle}
        aria-label={t(infoOpen ? 'action.close_info' : 'mobile.info')}
        title={t(infoOpen ? 'action.close_info' : 'mobile.info')}
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
      ><PanelRight size={16} aria-hidden="true" /></button>}
    </nav>
  );
}
