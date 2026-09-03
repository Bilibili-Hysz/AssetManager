import { type ReactNode } from 'react';
import { PanelRightClose, Menu, Grid3x3, CheckSquare } from 'lucide-react';
import { useDialogFocus } from '../../hooks/useDialogFocus';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { useI18n } from '../../hooks/useI18n';
import { StatusBar } from './StatusBar';
import { BottomSheet } from '../ui/BottomSheet';
import './Workspace.css';

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
  /** Keyboard resize: positive widens the panel (ArrowRight for sidebar). */
  onSidebarResizeStep?: (delta: number) => void;
  onInfoResizeStep?: (delta: number) => void;
  onSidebarToggle: () => void;
  onInfoToggle: () => void;
  onViewModeToggle?: () => void;
  viewMode?: 'grid' | 'list' | 'masonry';
  onSelectModeToggle?: () => void;
  selectMode?: boolean;
}

/**
 * AppLayout — Three-column layout container.
 *
 * All state (width, open/close) is managed by the parent component.
 * Drag handles are exposed via onDragStart callbacks.
 */
export function AppLayout({
  header, sidebar, infoPanel, children,
  sidebarOpen, infoOpen,
  sidebarWidth, infoWidth,
  onSidebarDragStart, onInfoDragStart,
  onSidebarResizeStep, onInfoResizeStep,
  onSidebarToggle, onInfoToggle,
  onViewModeToggle, viewMode = 'grid', onSelectModeToggle, selectMode = false,
}: AppLayoutProps) {
  const { t } = useI18n();
  const isMobile = useMediaQuery('(max-width: 768px)');
  const mobileDialog = isMobile && infoOpen ? 'info' : isMobile && sidebarOpen ? 'sidebar' : null;
  const mobileDialogRef = useDialogFocus(mobileDialog !== null, mobileDialog === 'info' ? onInfoToggle : onSidebarToggle);

  return (
    <div className="h-screen flex flex-col overflow-hidden transition-theme"
      style={{ backgroundColor: 'var(--color-bg)', color: 'var(--color-text)' }}>
      {/* ── Header ── */}
      {header && <div className="relative z-20 flex-shrink-0">{header}</div>}

      {/* ── Body: Three columns ── */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* ── Sidebar ── */}
        {sidebar && !isMobile && sidebarOpen && (
          <div
            className="relative flex-shrink-0 overflow-hidden transition-theme"
            style={{
              width: sidebarWidth,
              borderRight: '1px solid var(--color-border)',
              backgroundColor: 'var(--color-surface)',
            }}
          >
            {sidebar}
            {/* Drag handle */}
            <button
              type="button"
              className="absolute right-0 top-0 w-1.5 h-full cursor-col-resize z-10 transition-colors hover:opacity-100 opacity-0 focus-visible:opacity-100"
              aria-label={t('browse.resize_sidebar')}
              onMouseDown={onSidebarDragStart}
              onKeyDown={e => {
                if (e.key === 'ArrowRight') { e.preventDefault(); onSidebarResizeStep?.(32); }
                else if (e.key === 'ArrowLeft') { e.preventDefault(); onSidebarResizeStep?.(-32); }
              }}
            />
          </div>
        )}

        {/* Mobile sidebar overlay */}
        {sidebar && mobileDialog === 'sidebar' && (
          <>
            <div
              className="fixed inset-0 z-[var(--z-overlay)]"
              style={{ backgroundColor: 'var(--color-overlay)' }}
              onClick={onSidebarToggle}
              aria-hidden="true"
            />
            <div
              ref={mobileDialogRef}
              role="dialog"
              aria-modal="true"
              aria-label={t('mobile.menu')}
              tabIndex={-1}
              className="fixed inset-y-0 left-0 z-[var(--z-drawer)] w-72 overflow-hidden transition-theme"
              style={{
                borderRight: '1px solid var(--color-border)',
                backgroundColor: 'var(--color-surface)',
              }}
            >
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
          <div
            className="relative flex-shrink-0 overflow-hidden transition-theme"
            style={{
              width: infoWidth,
              borderLeft: '1px solid var(--color-border)',
              backgroundColor: 'var(--color-surface)',
            }}
          >
            {/* Drag handle */}
            <button
              type="button"
              className="absolute left-0 top-0 w-1.5 h-full cursor-col-resize z-10 transition-colors hover:opacity-100 opacity-0 focus-visible:opacity-100"
              aria-label={t('browse.resize_info')}
              onMouseDown={onInfoDragStart}
              onKeyDown={e => {
                if (e.key === 'ArrowLeft') { e.preventDefault(); onInfoResizeStep?.(32); }
                else if (e.key === 'ArrowRight') { e.preventDefault(); onInfoResizeStep?.(-32); }
              }}
            />
            {infoPanel}
          </div>
        )}

        {infoPanel && mobileDialog === 'info' && (
          <BottomSheet
            isOpen={true}
            onClose={() => onInfoToggle?.()}
            title={t('info.title')}
          >
            {infoPanel}
          </BottomSheet>
        )}
      </div>

      {/* ── Status Bar ── */}
      <StatusBar sidebarOpen={sidebarOpen} infoOpen={infoOpen} />

      {/* ── Mobile Bottom Bar ── */}
      {isMobile && (
        <div
          className="flex-shrink-0 flex items-center justify-around transition-theme z-30"
          style={{
            minHeight: 'calc(48px + env(safe-area-inset-bottom, 0px))',
            paddingBottom: 'env(safe-area-inset-bottom, 0px)',
            borderTop: '1px solid var(--color-border)',
            backgroundColor: 'var(--color-surface)',
          }}
        >
          <button
            type="button"
            onClick={onSidebarToggle}
            aria-label={t('mobile.menu')}
            className="touch-target flex flex-col items-center gap-0.5 p-2 transition-colors"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <Menu size={18} aria-hidden="true" />
            <span className="text-[10px]">{t('mobile.menu')}</span>
          </button>
          {onViewModeToggle && (
            <button
              type="button"
              onClick={onViewModeToggle}
              aria-label={t('mobile.view')}
              aria-pressed={viewMode === 'list'}
              className="touch-target flex flex-col items-center gap-0.5 p-2 transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <Grid3x3 size={18} aria-hidden="true" />
              <span className="text-[10px]">{t('mobile.view')}</span>
            </button>
          )}
          {infoPanel && (
            <button
              type="button"
              onClick={onInfoToggle}
              aria-label={t(infoOpen ? 'action.close_info' : 'mobile.info')}
              aria-expanded={infoOpen}
              className="touch-target flex flex-col items-center gap-0.5 p-2 transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <PanelRightClose size={18} aria-hidden="true" />
              <span className="text-[10px]">{t(infoOpen ? 'action.close_info' : 'mobile.info')}</span>
            </button>
          )}
          {onSelectModeToggle && (
            <button
              type="button"
              onClick={onSelectModeToggle}
              aria-label={t(selectMode ? 'mobile.done' : 'mobile.select')}
              aria-pressed={selectMode}
              className="touch-target flex flex-col items-center gap-0.5 p-2 transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <CheckSquare size={18} aria-hidden="true" />
              <span className="text-[10px]">{t(selectMode ? 'mobile.done' : 'mobile.select')}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
