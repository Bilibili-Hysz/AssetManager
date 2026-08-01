import { type ReactNode } from 'react';
import { PanelRightClose, Menu, Grid3x3, CheckSquare } from 'lucide-react';
import { useDialogFocus } from '../../hooks/useDialogFocus';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { useI18n } from '../../hooks/useI18n';
import { StatusBar } from './StatusBar';

interface AppLayoutProps {
  header?: ReactNode;
  sidebar?: ReactNode;
  infoPanel?: ReactNode;
  children: ReactNode;
  sidebarOpen: boolean;
  infoOpen: boolean;
  sidebarWidth: number;
  infoWidth: number;
  onSidebarDragStart: (e: React.MouseEvent) => void;
  onInfoDragStart: (e: React.MouseEvent) => void;
  onSidebarToggle: () => void;
  onInfoToggle: () => void;
  onViewModeToggle?: () => void;
  viewMode?: 'grid' | 'list';
  onSelectModeToggle?: () => void;
  selectMode?: boolean;
}

/**
 * AppLayout — 三栏布局容器。
 *
 * 所有状态（宽度、显隐）由父组件管理，本组件只负责渲染。
 * 拖拽 handle 通过 onDragStart 回调暴露给父组件，由父组件统一管理拖拽逻辑。
 */
export function AppLayout({
  header, sidebar, infoPanel, children,
  sidebarOpen, infoOpen,
  sidebarWidth, infoWidth,
  onSidebarDragStart, onInfoDragStart,
  onSidebarToggle, onInfoToggle,
  onViewModeToggle, viewMode = 'grid', onSelectModeToggle, selectMode = false,
}: AppLayoutProps) {
  const { t } = useI18n();
  const isMobile = useMediaQuery('(max-width: 768px)');
  const mobileDialog = isMobile && infoOpen ? 'info' : isMobile && sidebarOpen ? 'sidebar' : null;
  const mobileDialogRef = useDialogFocus(mobileDialog !== null, mobileDialog === 'info' ? onInfoToggle : onSidebarToggle);

  return (
    <div className="h-screen flex flex-col bg-slate-950 overflow-hidden">
      {/* ── Header ── */}
      {header && <div className="relative z-20 flex-shrink-0">{header}</div>}

      {/* ── Body: 三栏 ── */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* ── Sidebar ── */}
        {sidebar && !isMobile && sidebarOpen && (
          <div className="relative flex-shrink-0 overflow-hidden border-r border-slate-700 bg-slate-900" style={{ width: sidebarWidth }}>
            {sidebar}
            {/* Drag handle */}
            <div
              className="absolute right-0 top-0 w-1.5 h-full cursor-col-resize hover:bg-brand-500/50 active:bg-brand-500 transition-colors z-10"
              onMouseDown={onSidebarDragStart}
            />
          </div>
        )}

        {/* Mobile sidebar overlay */}
        {sidebar && mobileDialog === 'sidebar' && (
          <>
            <div className="fixed inset-0 bg-black/50 z-40" onClick={onSidebarToggle} aria-hidden="true" />
            <div ref={mobileDialogRef} role="dialog" aria-modal="true" aria-label={t('mobile.menu')} tabIndex={-1} className="fixed inset-y-0 left-0 z-50 w-72 overflow-hidden border-r border-slate-700 bg-slate-900">
              {sidebar}
            </div>
          </>
        )}

        {/* ── Main Content ── */}
        <main className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
          {children}
        </main>

        {/* ── Info Panel ── */}
        {infoPanel && !isMobile && infoOpen && (
          <div className="relative flex-shrink-0 overflow-hidden border-l border-slate-700 bg-slate-900" style={{ width: infoWidth }}>
            {/* Drag handle */}
            <div
              className="absolute left-0 top-0 w-1.5 h-full cursor-col-resize hover:bg-brand-500/50 active:bg-brand-500 transition-colors z-10"
              onMouseDown={onInfoDragStart}
            />
            {infoPanel}
          </div>
        )}

        {infoPanel && mobileDialog === 'info' && (
          <>
            <div className="fixed inset-0 bg-black/50 z-40" onClick={onInfoToggle} aria-hidden="true" />
            <div ref={mobileDialogRef} role="dialog" aria-modal="true" aria-label={t('info.title')} tabIndex={-1} className="fixed inset-x-0 bottom-0 z-50 max-h-[55vh] border-t border-slate-700 bg-slate-900">
              {infoPanel}
            </div>
          </>
        )}
      </div>

      {/* ── Status Bar ── */}
      <StatusBar sidebarOpen={sidebarOpen} infoOpen={infoOpen} />

      {/* ── Mobile Bottom Bar ── */}
      {isMobile && (
        <div className="flex-shrink-0 flex items-center justify-around h-12 border-t border-slate-700/50 bg-slate-900/90 backdrop-blur-sm">
            <button onClick={onSidebarToggle} aria-label={t('mobile.menu')} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
            <Menu size={18} aria-hidden="true" />
            <span className="text-[10px]">{t('mobile.menu')}</span>
          </button>
          {onViewModeToggle && (
            <button onClick={onViewModeToggle} aria-label={t('mobile.view')} aria-pressed={viewMode === 'list'} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
              <Grid3x3 size={18} aria-hidden="true" />
              <span className="text-[10px]">{t('mobile.view')}</span>
            </button>
          )}
          {infoPanel && (
            <button onClick={onInfoToggle} aria-label={t(infoOpen ? 'action.close_info' : 'mobile.info')} aria-expanded={infoOpen} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
              <PanelRightClose size={18} aria-hidden="true" />
              <span className="text-[10px]">{t(infoOpen ? 'action.close_info' : 'mobile.info')}</span>
            </button>
          )}
          {onSelectModeToggle && (
            <button onClick={onSelectModeToggle} aria-label={t(selectMode ? 'mobile.done' : 'mobile.select')} aria-pressed={selectMode} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
              <CheckSquare size={18} aria-hidden="true" />
              <span className="text-[10px]">{t(selectMode ? 'mobile.done' : 'mobile.select')}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
