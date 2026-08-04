// @vitest-environment jsdom
import { act, cleanup, fireEvent, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useDialogFocus } from './useDialogFocus';

describe('useDialogFocus', () => {
  afterEach(cleanup);

  function createContainer() {
    const container = document.createElement('div');
    container.innerHTML = `
      <button type="button">Trigger</button>
      <div tabindex="-1">
        <button type="button">First</button>
        <button type="button">Second</button>
      </div>
    `;
    document.body.appendChild(container);
    const dialog = container.querySelector('[tabindex="-1"]') as HTMLElement;
    const trigger = container.querySelector('button') as HTMLElement;
    return { container, dialog, trigger };
  }

  it('focuses the dialog when opened', () => {
    const { dialog } = createContainer();
    const onClose = vi.fn();

    renderHook(() => {
      const ref = useDialogFocus(true, onClose);
      // attach the ref to the dialog in the DOM
      Object.defineProperty(ref, 'current', { value: dialog, writable: false });
    });

    expect(document.activeElement).toBe(dialog);
  });

  it('calls onClose on Escape', () => {
    const { dialog } = createContainer();
    const onClose = vi.fn();

    renderHook(() => {
      const ref = useDialogFocus(true, onClose);
      Object.defineProperty(ref, 'current', { value: dialog, writable: false });
    });

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('traps Tab in a loop with focusable children', () => {
    const { dialog, trigger } = createContainer();
    const onClose = vi.fn();
    const buttons = dialog.querySelectorAll('button');
    const first = buttons[0] as HTMLElement;
    const last = buttons[1] as HTMLElement;

    renderHook(() => {
      const ref = useDialogFocus(true, onClose, trigger);
      Object.defineProperty(ref, 'current', { value: dialog, writable: false });
    });

    // Tab from last → wraps to first
    last.focus();
    act(() => {
      fireEvent.keyDown(document, { key: 'Tab' });
    });
    expect(document.activeElement).toBe(first);

    // Shift+Tab from first → wraps to last
    act(() => {
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    });
    expect(document.activeElement).toBe(last);
  });

  it('returns focus to the provided returnFocusTo element on unmount', () => {
    const { dialog, trigger } = createContainer();
    const onClose = vi.fn();

    const { unmount } = renderHook(() => {
      const ref = useDialogFocus(true, onClose, trigger);
      Object.defineProperty(ref, 'current', { value: dialog, writable: false });
    });

    unmount();
    expect(document.activeElement).toBe(trigger);
  });

  it('focuses the dialog when there are no focusable children', () => {
    const container = document.createElement('div');
    container.innerHTML = '<div tabindex="-1"></div>';
    document.body.appendChild(container);
    const dialog = container.querySelector('[tabindex="-1"]') as HTMLElement;
    const onClose = vi.fn();

    renderHook(() => {
      const ref = useDialogFocus(true, onClose);
      Object.defineProperty(ref, 'current', { value: dialog, writable: false });
    });

    // Tab should be trapped on the dialog itself
    act(() => {
      fireEvent.keyDown(document, { key: 'Tab' });
    });
    expect(document.activeElement).toBe(dialog);
  });

  it('does nothing when isOpen is false', () => {
    const { dialog } = createContainer();
    const onClose = vi.fn();

    renderHook(() => {
      const ref = useDialogFocus(false, onClose);
      Object.defineProperty(ref, 'current', { value: dialog, writable: false });
    });

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});
