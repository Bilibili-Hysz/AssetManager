import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useI18n } from '../../hooks/useI18n';

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
  const { t } = useI18n();
  const menuRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef(true);
  const [clamped, setClamped] = useState<{ x: number; y: number } | null>(null);

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

  // E9: clamp to the viewport using the menu's measured size instead of a fixed-width
  // estimate, so short menus near the bottom edge stay fully visible.
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const rect = menu.getBoundingClientRect();
    const margin = 8;
    const nextX = Math.max(margin, Math.min(x, window.innerWidth - rect.width - margin));
    const nextY = Math.max(margin, Math.min(y, window.innerHeight - rect.height - margin));
    setClamped({ x: nextX, y: nextY });
  }, [x, y]);

  // Roving focus within the menu (WCAG 2.1.1); Tab closes and returns focus
  // to the trigger instead of dumping it into the page behind the menu.
  const handleMenuKeyDown = (e: React.KeyboardEvent) => {
    const buttons = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
    if (buttons.length === 0) return;
    const currentIndex = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      buttons[(currentIndex + 1) % buttons.length]!.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      buttons[(currentIndex - 1 + buttons.length) % buttons.length]!.focus();
    } else if (e.key === 'Home') {
      e.preventDefault();
      buttons[0]!.focus();
    } else if (e.key === 'End') {
      e.preventDefault();
      buttons[buttons.length - 1]!.focus();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      restoreFocusRef.current = true;
      onClose();
    }
  };

  return (
    <div
      ref={menuRef}
      role="menu"
      onKeyDown={handleMenuKeyDown}
      className="fixed z-50 min-w-[180px] rounded-lg py-1"
      style={{
        left: clamped?.x ?? x,
        top: clamped?.y ?? y,
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-lg)',
      }}
      aria-label={t('action.actions')}
    >
      {items.map((item, i) => (
        item.divider ? (
          <div key={i} role="separator" className="my-1" style={{ borderTop: '1px solid var(--color-border)' }} />
        ) : (
          <button
            type="button"
            role="menuitem"
            key={i}
            className={`w-full flex items-center gap-3 px-3 py-2 text-sm text-left transition-colors`}
            style={{
              color: item.disabled ? 'var(--color-text-muted)' : 'var(--color-text)',
              opacity: item.disabled ? 0.5 : 1,
              cursor: item.disabled ? 'not-allowed' : 'pointer',
            }}
            onClick={() => {
              if (item.disabled) return;
              // A follow-up modal owns focus instead of restoring the menu trigger.
              restoreFocusRef.current = false;
              onClose();
              item.onClick();
            }}
            disabled={item.disabled}
          >
            {item.icon && <span className="w-4 h-4" style={{ color: 'var(--color-text-secondary)' }}>{item.icon}</span>}
            {item.label}
          </button>
        )
      ))}
    </div>
  );
}
