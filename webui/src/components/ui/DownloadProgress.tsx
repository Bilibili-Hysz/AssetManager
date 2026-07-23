import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import type { DownloadProgress as DownloadProgressValue } from '../../api/client';

export type DownloadProgressState =
  | { status: 'hidden'; progress: null; label: string }
  | { status: 'indeterminate'; progress: null; label: string }
  | { status: 'determinate'; progress: number; label: string };

interface DownloadProgressContextValue {
  start: (label?: string) => void;
  update: (progress: DownloadProgressValue) => void;
  finish: () => void;
}

const DownloadProgressContext = createContext<DownloadProgressContextValue | null>(null);

export function DownloadProgressProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DownloadProgressState>({ status: 'hidden', progress: null, label: 'Download in progress' });
  const start = useCallback((label = 'Download in progress') => setState({ status: 'indeterminate', progress: null, label }), []);
  const update = useCallback((next: DownloadProgressValue) => setState(previous => {
    if (next.total === null) return { status: 'indeterminate', progress: null, label: previous.label };
    return {
      status: 'determinate',
      progress: Math.min(100, (next.loaded / next.total) * 100),
      label: previous.label,
    };
  }), []);
  const finish = useCallback(() => setState(previous => ({ status: 'hidden', progress: null, label: previous.label })), []);

  return (
    <DownloadProgressContext.Provider value={{ start, update, finish }}>
      {children}
       {state.status !== 'hidden' && (
        <div
          className="fixed inset-x-0 top-0 z-[60] h-1 bg-slate-800"
          role="progressbar"
          aria-label={state.label}
          aria-busy="true"
          data-download-state={state.status}
          {...(state.status === 'determinate' ? {
            'aria-valuemin': 0,
            'aria-valuemax': 100,
            'aria-valuenow': Math.round(state.progress),
            'aria-valuetext': `${Math.round(state.progress)}%`,
          } : {})}
        >
          <div
            className={`h-full bg-indigo-500 transition-[width] duration-150 ${state.status === 'determinate' ? '' : 'animate-pulse w-1/3'}`}
            style={state.status === 'determinate' ? { width: `${state.progress}%` } : undefined}
          />
        </div>
      )}
    </DownloadProgressContext.Provider>
  );
}

export function useDownloadProgress(): DownloadProgressContextValue {
  const context = useContext(DownloadProgressContext);
  if (!context) throw new Error('useDownloadProgress must be used within DownloadProgressProvider');
  return context;
}
