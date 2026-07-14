import { useEffect, useRef, type ReactNode } from 'react';

interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  divider?: boolean;
}

interface ContextMenuProps {
  x: number;
  y: number;
  items: MenuItem[];
  trigger?: HTMLElement | null;
  onClose: () => void;
}

export function ContextMenu({ x, y, items, trigger, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef(true);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    // Delay listener to avoid immediate close from the right-click itself
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClick);
      document.addEventListener('keydown', handleEsc);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleEsc);
    };
  }, [onClose]);

  useEffect(() => {
    const firstAction = menuRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)');
    firstAction?.focus();
    return () => {
      if (restoreFocusRef.current) trigger?.focus();
    };
  }, [trigger]);

  // Adjust position to stay within viewport
  const adjustedX = Math.min(x, window.innerWidth - 200);
  const adjustedY = Math.min(y, window.innerHeight - items.length * 40);

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[180px] rounded-lg bg-slate-800 border border-slate-600/50 shadow-xl py-1"
      style={{ left: adjustedX, top: adjustedY }}
      aria-label="Actions"
    >
      {items.map((item, i) => (
        item.divider ? (
          <div key={i} className="my-1 border-t border-slate-700/50" />
        ) : (
          <button
            key={i}
            className={`w-full flex items-center gap-3 px-3 py-2 text-sm text-left transition-colors
              ${item.disabled ? 'text-slate-600 cursor-not-allowed' : 'text-slate-200 hover:bg-slate-700/50'}`}
            onClick={() => {
              if (item.disabled) return;
              // A follow-up modal owns focus instead of restoring the menu trigger.
              restoreFocusRef.current = false;
              onClose();
              item.onClick();
            }}
            disabled={item.disabled}
          >
            {item.icon && <span className="w-4 h-4 text-slate-400">{item.icon}</span>}
            {item.label}
          </button>
        )
      ))}
    </div>
  );
}
