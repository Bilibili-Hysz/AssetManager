// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppLayout } from './AppLayout';
import { setLang, t } from '../../i18n';

vi.mock('./StatusBar', () => ({
  StatusBar: () => null,
}));

describe('AppLayout', () => {
  afterEach(cleanup);
  it('labels and exposes state for the mobile information action', () => {
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

    const openButton = screen.getByRole('button', { name: '打开信息面板' });
    expect(openButton.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(openButton);
  });

  it.each(['zh', 'ja'] as const)('uses the %s translation for mobile dialog labels', lang => {
    setLang(lang);
    window.matchMedia = () => ({ matches: true, media: '(max-width: 768px)', onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => true });
    const props = { sidebarWidth: 240, infoWidth: 320, onSidebarDragStart: () => {}, onInfoDragStart: () => {}, onSidebarToggle: () => {}, onInfoToggle: () => {} };
    const view = render(<AppLayout {...props} infoPanel={<aside>Info</aside>} sidebar={<aside>Nav</aside>} sidebarOpen={true} infoOpen={false}><div>Content</div></AppLayout>);
    expect(screen.getByRole('dialog', { name: t('mobile.menu') })).toBeDefined();
    view.rerender(<AppLayout {...props} infoPanel={<aside>Info</aside>} sidebar={<aside>Nav</aside>} sidebarOpen={false} infoOpen={true}><div>Content</div></AppLayout>);
    expect(screen.getByRole('dialog', { name: t('info.title') })).toBeDefined();
  });

  it('wires mobile information and selection controls with their active states', () => {
    setLang('en');
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
    const onInfoToggle = vi.fn();
    const onSelectModeToggle = vi.fn();

    render(
      <AppLayout
        infoPanel={<aside>Info</aside>}
        sidebarOpen={false}
        infoOpen={false}
        selectMode={true}
        sidebarWidth={240}
        infoWidth={320}
        onSidebarDragStart={() => {}}
        onInfoDragStart={() => {}}
        onSidebarToggle={() => {}}
        onInfoToggle={onInfoToggle}
        onSelectModeToggle={onSelectModeToggle}
      >
        <div>Content</div>
      </AppLayout>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open information panel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onInfoToggle).toHaveBeenCalledOnce();
    expect(onSelectModeToggle).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Done' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('exposes the mobile view control as a pressed state', () => {
    setLang('en');
    window.matchMedia = () => ({ matches: true, media: '(max-width: 768px)', onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => true });
    render(
      <AppLayout sidebarOpen={false} infoOpen={false} sidebarWidth={240} infoWidth={320} onSidebarDragStart={() => {}} onInfoDragStart={() => {}} onSidebarToggle={() => {}} onInfoToggle={() => {}} onViewModeToggle={() => {}}>
        <div>Content</div>
      </AppLayout>,
    );
    expect(screen.getByRole('button', { name: 'View' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('labels the mobile information action as close when open', () => {
    setLang('en');
    window.matchMedia = () => ({ matches: true, media: '(max-width: 768px)', onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => true });
    render(
      <AppLayout infoPanel={<aside>Info</aside>} sidebarOpen={false} infoOpen={true} sidebarWidth={240} infoWidth={320} onSidebarDragStart={() => {}} onInfoDragStart={() => {}} onSidebarToggle={() => {}} onInfoToggle={() => {}}><div>Content</div></AppLayout>,
    );
    const closeButton = screen.getByRole('button', { name: 'Close information panel' });
    expect(closeButton.getAttribute('aria-expanded')).toBe('true');
  });

  it('exposes mobile view and selection controls as pressed states', () => {
    setLang('en');
    window.matchMedia = () => ({ matches: true, media: '(max-width: 768px)', onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => true });
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
        onViewModeToggle={() => {}}
        viewMode="list"
        onSelectModeToggle={() => {}}
        selectMode={true}
      >
        <div>Content</div>
      </AppLayout>,
    );

    expect(screen.getByRole('button', { name: 'View' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Done' }).getAttribute('aria-pressed')).toBe('true');
  });
});
