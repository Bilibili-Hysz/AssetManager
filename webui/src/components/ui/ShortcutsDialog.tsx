import { Modal } from './Modal';
import { useI18n } from '../../hooks/useI18n';
import { SHORTCUT_SCOPES, shortcutsByScope } from '../../shortcuts/registry';
import './ShortcutsDialog.css';

interface ShortcutsDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Keyboard shortcut cheat sheet (design line A3). Opens on `?` (App.tsx
 * global listener) and from the command palette entry; renders straight from
 * webui/src/shortcuts/registry.ts so the dialog can never drift from the
 * actually implemented shortcuts. Built on Modal for the focus trap, Esc
 * handling, and axe-scanned scrim.
 */
export function ShortcutsDialog({ open, onClose }: ShortcutsDialogProps) {
  const { t } = useI18n();
  return (
    <Modal open={open} onClose={onClose} title={t('shortcuts.title')} maxWidth="max-w-xl">
      {/* The list container scrolls on small viewports; make the scrollable
          region keyboard-accessible (axe scrollable-region-focusable). */}
      <div
        className="shortcuts-dialog"
        role="group"
        aria-label={t('shortcuts.title')}
        tabIndex={0}
      >
        {SHORTCUT_SCOPES.map(scope => {
          const entries = shortcutsByScope(scope);
          if (entries.length === 0) return null;
          return (
            <section key={scope} className="shortcuts-dialog-group" aria-labelledby={`shortcuts-group-${scope}`}>
              <h4 id={`shortcuts-group-${scope}`} className="shortcuts-dialog-group-title">
                {t(`shortcuts.group_${scope}`)}
              </h4>
              <ul className="shortcuts-dialog-list">
                {entries.map(entry => (
                  <li key={entry.descriptionKey} className="shortcuts-dialog-row" data-testid="shortcuts-row">
                    <span className="shortcuts-dialog-keys">
                      {entry.keys.map(key => <kbd key={key}>{key}</kbd>)}
                    </span>
                    <span className="shortcuts-dialog-description">{t(entry.descriptionKey)}</span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </Modal>
  );
}
