// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AppLayout } from './AppLayout';
import { setLang } from '../../i18n';

vi.mock('./StatusBar', () => ({
  StatusBar: () => null,
}));

describe('AppLayout', () => {
  it('labels the mobile information action in the active language', () => {
    setLang('zh');
    window.matchMedia = () => ({
      matches: true,
      media: '(max-width: 768px)',
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => true,
    });

    render(
      <AppLayout
        infoPanel={<aside>Info</aside>}
        sidebarOpen={false}
        infoOpen={false}
        sidebarWidth={240}
        infoWidth={320}
        onSidebarDragStart={() => {}}
        onInfoDragStart={() => {}}
        onSidebarToggle={() => {}}
        onInfoToggle={() => {}}
      >
        <div>Content</div>
      </AppLayout>,
    );

    expect(screen.getByRole('button', { name: '打开信息面板' })).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: '打开信息面板' }));
  });
});
