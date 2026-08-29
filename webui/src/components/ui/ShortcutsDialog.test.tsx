// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ShortcutsDialog } from './ShortcutsDialog';
import { SHORTCUTS, SHORTCUT_SCOPES, shortcutsByScope } from '../../shortcuts/registry';

describe('ShortcutsDialog', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('renders nothing while closed', () => {
    render(<ShortcutsDialog open={false} onClose={() => {}} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders one row per registry entry, grouped by scope', () => {
    render(<ShortcutsDialog open={true} onClose={() => {}} />);

    const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(dialog).toBeDefined();

    // Groups render in registry scope order with localized headers (h4;
    // the Modal's own h3 title is excluded).
    const groupTitles = screen.getAllByRole('heading', { level: 4 });
    expect(groupTitles.map(h => h.textContent)).toEqual(
      SHORTCUT_SCOPES.map(scope => {
        switch (scope) {
          case 'global': return 'Global';
          case 'workspace': return 'Workspace (file list focused)';
          default: return 'Dialogs & viewer';
        }
      }),
    );

    // Every registry entry becomes exactly one visible row: the dialog is a
    // pure projection of the registry (anti-drift guarantee).
    expect(screen.getAllByTestId('shortcuts-row').length).toBe(SHORTCUTS.length);
    expect(screen.getAllByTestId('shortcuts-row').length).toBeGreaterThan(0);
    for (const scope of SHORTCUT_SCOPES) {
      const group = document.getElementById(`shortcuts-group-${scope}`);
      expect(group).toBeDefined();
      const list = group?.parentElement?.querySelector('ul');
      expect(list?.children.length).toBe(shortcutsByScope(scope).length);
    }
  });

  it('shows the ? help key and closes via the close button', () => {
    const onClose = vi.fn();
    render(<ShortcutsDialog open={true} onClose={onClose} />);

    expect(screen.getByText('Keyboard shortcuts')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
