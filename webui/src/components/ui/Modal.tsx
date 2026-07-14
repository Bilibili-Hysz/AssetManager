import { useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { useDialogFocus } from '../../hooks/useDialogFocus';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  maxWidth?: string;
  returnFocusTo?: HTMLElement | null;
}

export function Modal({ open, onClose, title, children, maxWidth = 'max-w-lg', returnFocusTo }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useDialogFocus(open, onClose, returnFocusTo);
  const titleId = useId();

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : 'Dialog'}
        tabIndex={-1}
        className={`w-full ${maxWidth} mx-4 rounded-xl bg-slate-900 border border-slate-700/50 shadow-2xl`}
      >
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
            <h3 id={titleId} className="text-lg font-semibold text-white">{title}</h3>
            <button onClick={onClose} aria-label="Close dialog" className="text-slate-400 hover:text-white transition-colors">
              <X size={20} />
            </button>
          </div>
        )}
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}
