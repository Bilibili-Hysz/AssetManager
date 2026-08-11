import { useState, useCallback, createContext, useContext, type ReactNode } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';

type ToastType = 'success' | 'error' | 'info';

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);
let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = nextId++;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map(toast => (
          <div
            key={toast.id}
            role={toast.type === 'error' ? 'alert' : 'status'}
            aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
            className="flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg backdrop-blur-sm transition-theme"
            style={{
              backgroundColor: toast.type === 'success' ? 'var(--color-success-subtle)' :
                toast.type === 'error' ? 'var(--color-danger-subtle)' : 'var(--color-surface)',
              border: `1px solid ${toast.type === 'success' ? 'var(--color-success)' :
                toast.type === 'error' ? 'var(--color-danger)' : 'var(--color-border)'}`,
              color: 'var(--color-text)',
            }}
          >
            {toast.type === 'success' ? <CheckCircle size={18} aria-hidden="true" style={{ color: 'var(--color-success)' }} /> :
             toast.type === 'error' ? <AlertCircle size={18} aria-hidden="true" style={{ color: 'var(--color-danger)' }} /> :
             <Info size={18} aria-hidden="true" style={{ color: 'var(--color-info)' }} />}
            <span className="text-sm flex-1">{toast.message}</span>
            <button
              type="button"
              aria-label={t('action.close')}
              onClick={() => dismiss(toast.id)}
              className="opacity-60 hover:opacity-100 transition-opacity"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
