// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Modal } from './Modal';

describe('Modal', () => {
  afterEach(cleanup);

  function renderModal(overrides: Record<string, unknown> = {}) {
    const onClose = vi.fn();
    const utils = render(
      <Modal open={true} onClose={onClose} {...overrides}>
        <button type="button">Inside</button>
      </Modal>,
    );
    return { onClose, utils };
  }

  it('renders nothing when closed', () => {
    render(<Modal open={false} onClose={vi.fn()}>x</Modal>);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders the dialog with title and children', () => {
    renderModal({ title: 'Confirm' });
    expect(screen.getByRole('dialog')).toBeDefined();
    expect(screen.getByText('Confirm')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Inside' })).toBeDefined();
  });

  it('wires aria-labelledby to the title and falls back to aria-label without a title', () => {
    const withTitle = renderModal({ title: 'Confirm' });
    const labelled = withTitle.utils.getByRole('dialog') as HTMLElement;
    const heading = withTitle.utils.getByText('Confirm') as HTMLElement;
    expect(labelled.getAttribute('aria-labelledby')).toBe(heading.id);

    cleanup();
    const noTitle = renderModal({});
    const unlabelled = noTitle.utils.getByRole('dialog') as HTMLElement;
    expect(unlabelled.getAttribute('aria-label')).toBe('Dialog');
  });

  it('focuses the dialog on open', () => {
    renderModal();
    expect(document.activeElement).toBe(screen.getByRole('dialog'));
  });

  it('closes via the header close button', () => {
    const { onClose } = renderModal({ title: 'Confirm' });
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes on an overlay click but not on a dialog content click', () => {
    const { onClose, utils } = renderModal();
    const overlay = utils.container.firstElementChild as HTMLElement;
    fireEvent.click(screen.getByRole('button', { name: 'Inside' }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(overlay);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes on Escape', () => {
    const { onClose } = renderModal();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('traps Tab focus between the first and last focusable elements', () => {
    render(
      <Modal open={true} onClose={vi.fn()}>
        <button type="button">First</button>
        <button type="button">Second</button>
      </Modal>,
    );
    const first = screen.getByRole('button', { name: 'First' }) as HTMLElement;
    const last = screen.getByRole('button', { name: 'Second' }) as HTMLElement;

    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('returns focus to the provided element when closed', () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    const utils = render(<Modal open={true} onClose={vi.fn()} returnFocusTo={trigger}>x</Modal>);
    utils.rerender(<Modal open={false} onClose={vi.fn()} returnFocusTo={trigger}>x</Modal>);
    expect(document.activeElement).toBe(trigger);
  });
});
