import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { useDialogFocus } from '../../hooks/useDialogFocus';
import { useI18n } from '../../hooks/useI18n';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  maxWidth?: string;
  returnFocusTo?: HTMLElement | null;
}

export function Modal({ open, onClose, title, children, maxWidth = 'max-w-lg', returnFocusTo }: ModalProps) {
  const { t } = useI18n();
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useDialogFocus(open, onClose, returnFocusTo);
  const titleId = useId();

  // E7: lock body scroll while a modal is open and restore it when it closes/unmounts.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [open]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm"
      style={{ backgroundColor: 'var(--color-overlay)' }}
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : t('ui.dialog')}
        tabIndex={-1}
        className={`w-full ${maxWidth} mx-4 rounded-xl transition-theme`}
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-xl)',
        }}
      >
        {title && (
          <div
            className="flex items-center justify-between px-6 py-4"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <h3 id={titleId} className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>{title}</h3>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('action.close_dialog')}
              className="transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <X size={20} />
            </button>
          </div>
        )}
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}
