/**
 * Single source of truth for every implemented WebUI keyboard shortcut.
 *
 * The shortcuts help dialog (ShortcutsDialog) renders from this registry, so
 * a shortcut added in code without a registry entry (or vice versa) is a
 * review/gate-visible drift — the same anti-drift idea as the desktop's
 * FILE_LIST_SHORTCUTS. Key labels here are display strings; the actual
 * keydown handling lives next to each feature (App.tsx, AppHeader,
 * BrowsePage, CommandPalette, ImageViewer, Modal/useDialogFocus).
 */

export type ShortcutScope = 'global' | 'workspace' | 'dialog';

export interface ShortcutEntry {
  /** Display key labels, e.g. ['Ctrl', 'K'] or ['←']. */
  keys: string[];
  scope: ShortcutScope;
  /** i18n key (shortcuts.* namespace) describing what the shortcut does. */
  descriptionKey: string;
}

/** Render order of scope groups in the help dialog. */
export const SHORTCUT_SCOPES: readonly ShortcutScope[] = ['global', 'workspace', 'dialog'] as const;

export const SHORTCUTS: readonly ShortcutEntry[] = [
  // ── Global (work on every page, outside editable fields) ──
  { keys: ['Ctrl', 'K'], scope: 'global', descriptionKey: 'shortcuts.command_palette' },
  { keys: ['/'], scope: 'global', descriptionKey: 'shortcuts.focus_search' },
  { keys: ['?'], scope: 'global', descriptionKey: 'shortcuts.help' },
  { keys: ['Esc'], scope: 'global', descriptionKey: 'shortcuts.escape' },
  // ── Workspace (only while the file list has focus) ──
  { keys: ['g'], scope: 'workspace', descriptionKey: 'shortcuts.toggle_view' },
  { keys: ['s'], scope: 'workspace', descriptionKey: 'shortcuts.toggle_select' },
  // ── Dialogs & viewer ──
  { keys: ['↑', '↓'], scope: 'dialog', descriptionKey: 'shortcuts.palette_navigate' },
  { keys: ['Enter'], scope: 'dialog', descriptionKey: 'shortcuts.palette_open' },
  { keys: ['←', '→'], scope: 'dialog', descriptionKey: 'shortcuts.viewer_navigate' },
  { keys: ['0'], scope: 'dialog', descriptionKey: 'shortcuts.viewer_reset' },
] as const;

export function shortcutsByScope(scope: ShortcutScope): readonly ShortcutEntry[] {
  return SHORTCUTS.filter(entry => entry.scope === scope);
}
