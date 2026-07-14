import { type ReactNode } from 'react';
import { PanelLeftClose, PanelRightClose, Menu, Grid3x3, CheckSquare } from 'lucide-react';
import { useMediaQuery } from '../../hooks/useMediaQuery';
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
  onSelectModeToggle?: () => void;
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
  onViewModeToggle, onSelectModeToggle,
}: AppLayoutProps) {
  const isMobile = useMediaQuery('(max-width: 768px)');

  return (
    <div className="h-screen flex flex-col bg-slate-950 overflow-hidden">
      {/* ── Header ── */}
      {header && <div className="flex-shrink-0">{header}</div>}

      {/* ── Body: 三栏 ── */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Sidebar toggle button (desktop, when sidebar is closed) */}
        {sidebar && !isMobile && !sidebarOpen && (
          <button
            onClick={onSidebarToggle}
            className="absolute left-0 top-2 z-30 p-1 text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 rounded-r-md transition-colors"
            title="Open sidebar"
          >
            <PanelLeftClose size={16} />
          </button>
        )}

        {/* ── Sidebar ── */}
        {sidebar && !isMobile && sidebarOpen && (
          <div className="flex-shrink-0 border-r border-slate-700/50 overflow-hidden relative" style={{ width: sidebarWidth }}>
            {sidebar}
            {/* Drag handle */}
            <div
              className="absolute right-0 top-0 w-1.5 h-full cursor-col-resize hover:bg-brand-500/50 active:bg-brand-500 transition-colors z-10"
              onMouseDown={onSidebarDragStart}
            />
          </div>
        )}

        {/* Mobile sidebar overlay */}
        {sidebar && isMobile && sidebarOpen && (
          <>
            <div className="fixed inset-0 bg-black/50 z-40" onClick={onSidebarToggle} />
            <div className="fixed inset-y-0 left-0 z-50 w-72 bg-slate-900 border-r border-slate-700/50 shadow-xl overflow-hidden">
              {sidebar}
            </div>
          </>
        )}

        {/* ── Main Content ── */}
        <main className="flex-1 overflow-auto min-w-0">
          {children}
        </main>

        {/* Info panel toggle button (desktop, when info is closed) */}
        {infoPanel && !isMobile && !infoOpen && (
          <button
            onClick={onInfoToggle}
            className="absolute right-0 top-2 z-30 p-1 text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 rounded-l-md transition-colors"
            title="Open info panel"
          >
            <PanelRightClose size={16} />
          </button>
        )}

        {/* ── Info Panel ── */}
        {infoPanel && !isMobile && infoOpen && (
          <div className="flex-shrink-0 border-l border-slate-700/50 overflow-hidden relative" style={{ width: infoWidth }}>
            {/* Drag handle */}
            <div
              className="absolute left-0 top-0 w-1.5 h-full cursor-col-resize hover:bg-brand-500/50 active:bg-brand-500 transition-colors z-10"
              onMouseDown={onInfoDragStart}
            />
            {infoPanel}
          </div>
        )}
      </div>

      {/* ── Status Bar ── */}
      <StatusBar sidebarOpen={sidebarOpen} infoOpen={infoOpen} />

      {/* ── Mobile Bottom Bar ── */}
      {isMobile && (
        <div className="flex-shrink-0 flex items-center justify-around h-12 border-t border-slate-700/50 bg-slate-900/90 backdrop-blur-sm">
          <button onClick={onSidebarToggle} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
            <Menu size={18} />
            <span className="text-[10px]">Menu</span>
          </button>
          {onViewModeToggle && (
            <button onClick={onViewModeToggle} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
              <Grid3x3 size={18} />
              <span className="text-[10px]">View</span>
            </button>
          )}
          {onSelectModeToggle && (
            <button onClick={onSelectModeToggle} className="flex flex-col items-center gap-0.5 p-2 text-slate-400">
              <CheckSquare size={18} />
              <span className="text-[10px]">Select</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}