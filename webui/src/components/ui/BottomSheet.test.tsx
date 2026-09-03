// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BottomSheet } from './BottomSheet';

describe('BottomSheet', () => {
  afterEach(cleanup);

  it('renders nothing when isOpen is false', () => {
    render(
      <BottomSheet isOpen={false} onClose={vi.fn()}>
        <div>Content</div>
      </BottomSheet>,
    );
    expect(screen.queryByTestId('bottom-sheet')).toBeNull();
  });

  it('renders sheet with children and grabber when isOpen is true', () => {
    const onClose = vi.fn();
    render(
      <BottomSheet isOpen={true} onClose={onClose} title="Details Drawer">
        <div>Sheet Content</div>
      </BottomSheet>,
    );

    const sheet = screen.getByTestId('bottom-sheet');
    expect(sheet).toBeDefined();
    expect(screen.getByText('Sheet Content')).toBeDefined();
    expect(screen.getByTestId('bottom-sheet-grabber')).toBeDefined();
    expect(sheet.getAttribute('aria-label')).toBe('Details Drawer');
  });

  it('handles touch drag down to close from peek snap', () => {
    const onClose = vi.fn();
    render(
      <BottomSheet isOpen={true} onClose={onClose} initialSnap="peek">
        <div>Scrollable Content</div>
      </BottomSheet>,
    );

    const sheet = screen.getByTestId('bottom-sheet');
    fireEvent.touchStart(sheet, {
      touches: [{ clientY: 100 }],
    });
    fireEvent.touchMove(sheet, {
      touches: [{ clientY: 300 }],
    });
    fireEvent.touchEnd(sheet);

    expect(onClose).toHaveBeenCalled();
  });
});
