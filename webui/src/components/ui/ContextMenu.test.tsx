// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContextMenu } from './ContextMenu';

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

function setup({ x = 100, y = 100, items }: { x?: number; y?: number; items: Array<Record<string, unknown>> }) {
  const onClose = vi.fn();
  const trigger = document.createElement('button');
  document.body.appendChild(trigger);
  const utils = render(
    <ContextMenu
      x={x}
      y={y}
      items={items as Array<{ label: string; onClick: () => void; disabled?: boolean; divider?: boolean }>}
      trigger={trigger}
      onClose={onClose}
    />,
  );
  return { onClose, trigger, utils };
}

async function flushListeners() {
  await act(async () => { await new Promise(r => setTimeout(r, 0)); });
}

describe('ContextMenu', () => {
  afterEach(cleanup);

  it('renders enabled and disabled items', () => {
    setup({
      items: [
        { label: 'Open', onClick: vi.fn() },
        { label: 'Banned', onClick: vi.fn(), disabled: true },
      ],
    });
    const open = screen.getByRole('button', { name: 'Open' }) as HTMLButtonElement;
    const banned = screen.getByRole('button', { name: 'Banned' }) as HTMLButtonElement;
    expect(open).toBeDefined();
    expect(banned.disabled).toBe(true);
  });

  it('focuses the first non-disabled item on mount', () => {
    setup({
      items: [
        { label: 'Banned', onClick: vi.fn(), disabled: true },
        { label: 'Open', onClick: vi.fn() },
      ],
    });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open' }));
  });

  it('closes and runs the action when an enabled item is clicked', () => {
    const onClick = vi.fn();
    const { onClose } = setup({ items: [{ label: 'Open', onClick }] });
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('ignores clicks on disabled items', () => {
    const onClick = vi.fn();
    const { onClose } = setup({ items: [{ label: 'Banned', onClick, disabled: true }] });
    fireEvent.click(screen.getByRole('button', { name: 'Banned' }));
    expect(onClick).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape', async () => {
    const { onClose } = setup({ items: [{ label: 'Open', onClick: vi.fn() }] });
    await flushListeners();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes on an outside mousedown but not on an inside one', async () => {
    const { onClose } = setup({ items: [{ label: 'Open', onClick: vi.fn() }] });
    await flushListeners();
    fireEvent.mouseDown(screen.getByRole('button', { name: 'Open' }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('stays within the viewport by clamping coordinates', () => {
    setup({ x: 10_000, y: 10_000, items: [{ label: 'Open', onClick: vi.fn() }] });
    const menu = screen.getByLabelText('action.actions') as HTMLElement;
    expect(menu.style.left).toBe(`${window.innerWidth - 200}px`);
    expect(menu.style.top).toBe(`${window.innerHeight - 40}px`);
  });

  it('restores focus to the trigger on unmount unless an action was chosen', () => {
    const { trigger, utils } = setup({ items: [{ label: 'Open', onClick: vi.fn() }] });
    utils.unmount();
    expect(document.activeElement).toBe(trigger);
  });
});
