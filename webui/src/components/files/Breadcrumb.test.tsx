// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Breadcrumb } from './Breadcrumb';

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'action.close_sidebar': 'Close sidebar',
      'action.open_sidebar': 'Open sidebar',
      'action.close_info': 'Close information panel',
      'mobile.info': 'Open information panel',
    }[key] ?? key),
  }),
}));

describe('Breadcrumb', () => {
  it('places panel controls on either side of breadcrumb navigation', () => {
    render(<Breadcrumb path="assets/icons" onNavigate={vi.fn()} onSidebarToggle={vi.fn()} onInfoToggle={vi.fn()} sidebarOpen infoOpen />);

    const row = screen.getByRole('navigation', { name: 'Workspace navigation' });
    expect(row.firstElementChild?.getAttribute('aria-label')).toBe('Close sidebar');
    expect(row.lastElementChild?.getAttribute('aria-label')).toBe('Close information panel');
  });

  it('fires the panel controls independently', () => {
    const onSidebarToggle = vi.fn();
    const onInfoToggle = vi.fn();
    render(<Breadcrumb path="" onNavigate={vi.fn()} onSidebarToggle={onSidebarToggle} onInfoToggle={onInfoToggle} sidebarOpen={false} infoOpen={false} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open sidebar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open information panel' }));
    expect(onSidebarToggle).toHaveBeenCalledOnce();
    expect(onInfoToggle).toHaveBeenCalledOnce();
  });
});
