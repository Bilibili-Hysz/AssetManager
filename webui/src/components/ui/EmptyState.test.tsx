// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  afterEach(cleanup);

  describe('Illustration Types Rendering', () => {
    it('renders directory type by default with isometric archive and float cube', () => {
      const { container } = render(<EmptyState />);
      expect(screen.getByTestId('empty-state-illustration-directory')).toBeDefined();
      expect(container.querySelector('.dark-archive-float')).toBeDefined();
      expect(container.querySelector('.dark-archive-float-shadow')).toBeDefined();
      expect(screen.getByText('档案库为空')).toBeDefined();
      expect(screen.getByText('当前目录中没有可显示的内容或资源。')).toBeDefined();
    });

    it('renders search type with radar sweep beam and reticle elements', () => {
      const { container } = render(<EmptyState type="search" />);
      expect(screen.getByTestId('empty-state-illustration-search')).toBeDefined();
      expect(container.querySelector('.dark-archive-radar-sweep')).toBeDefined();
      expect(screen.getByText('未检索到匹配结果')).toBeDefined();
      expect(screen.getByText('未找到符合检索条件的资源，请调整关键词或过滤条件。')).toBeDefined();
    });

    it('renders offline type with severed link nodes and amber pulse ripples', () => {
      const { container } = render(<EmptyState type="offline" />);
      expect(screen.getByTestId('empty-state-illustration-offline')).toBeDefined();
      const pulses = container.querySelectorAll('.dark-archive-pulse');
      expect(pulses.length).toBeGreaterThanOrEqual(3);
      expect(screen.getByText('连接已中断')).toBeDefined();
      expect(screen.getByText('无法连接到资源库服务，请检查网络或服务状态。')).toBeDefined();
    });
  });

  describe('Custom Text & Content', () => {
    it('renders custom title and description', () => {
      render(
        <EmptyState
          type="directory"
          title="Custom Directory Title"
          description="Custom directory description text"
        />,
      );
      expect(screen.getByRole('heading', { level: 3, name: 'Custom Directory Title' })).toBeDefined();
      expect(screen.getByText('Custom directory description text')).toBeDefined();
    });

    it('renders children content when provided', () => {
      render(
        <EmptyState title="Title">
          <div data-testid="custom-child">Child Element</div>
        </EmptyState>,
      );
      expect(screen.getByTestId('custom-child')).toBeDefined();
      expect(screen.getByText('Child Element')).toBeDefined();
    });

    it('handles empty or null title/description gracefully', () => {
      render(<EmptyState title={null} description={null} />);
      expect(screen.queryByRole('heading')).toBeNull();
      expect(screen.queryByText('档案库为空')).toBeNull();
    });
  });

  describe('Action Buttons & Handlers', () => {
    it('renders primaryAction and secondaryAction config objects and triggers onClick', () => {
      const onPrimary = vi.fn();
      const onSecondary = vi.fn();

      render(
        <EmptyState
          title="Action Test"
          primaryAction={{
            label: 'Retry Scan',
            onClick: onPrimary,
            'data-testid': 'primary-btn',
          }}
          secondaryAction={{
            label: 'Go Home',
            onClick: onSecondary,
            'data-testid': 'secondary-btn',
          }}
        />,
      );

      const primaryBtn = screen.getByTestId('primary-btn');
      const secondaryBtn = screen.getByTestId('secondary-btn');

      expect(primaryBtn).toBeDefined();
      expect(secondaryBtn).toBeDefined();
      expect(primaryBtn.className).toContain('empty-state-btn-primary');
      expect(secondaryBtn.className).toContain('empty-state-btn-secondary');

      fireEvent.click(primaryBtn);
      expect(onPrimary).toHaveBeenCalledTimes(1);

      fireEvent.click(secondaryBtn);
      expect(onSecondary).toHaveBeenCalledTimes(1);
    });

    it('renders link when href is specified in action config', () => {
      render(
        <EmptyState
          title="Link Test"
          primaryAction={{
            label: 'Open Docs',
            href: '/docs',
            'data-testid': 'link-btn',
          }}
        />,
      );

      const linkBtn = screen.getByTestId('link-btn');
      expect(linkBtn.tagName.toLowerCase()).toBe('a');
      expect(linkBtn.getAttribute('href')).toBe('/docs');
    });

    it('renders disabled action button when disabled is true', () => {
      const onClick = vi.fn();
      render(
        <EmptyState
          title="Disabled Test"
          primaryAction={{
            label: 'Disabled Action',
            onClick,
            disabled: true,
            'data-testid': 'disabled-btn',
          }}
        />,
      );

      const btn = screen.getByTestId('disabled-btn') as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      fireEvent.click(btn);
      expect(onClick).not.toHaveBeenCalled();
    });

    it('renders custom JSX element for actions', () => {
      render(
        <EmptyState
          title="Custom Node Test"
          primaryAction={<button type="button" data-testid="custom-jsx-btn">Custom JSX</button>}
        />,
      );

      expect(screen.getByTestId('custom-jsx-btn')).toBeDefined();
      expect(screen.getByText('Custom JSX')).toBeDefined();
    });

    it('renders action with icon properly', () => {
      render(
        <EmptyState
          title="Icon Test"
          primaryAction={{
            label: 'With Icon',
            icon: <span data-testid="test-icon">★</span>,
          }}
        />,
      );

      expect(screen.getByTestId('test-icon')).toBeDefined();
      expect(screen.getByText('With Icon')).toBeDefined();
    });
  });
});
