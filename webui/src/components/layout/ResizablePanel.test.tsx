// @vitest-environment jsdom
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ResizablePanel } from './ResizablePanel';

function setup(overrides: Record<string, unknown> = {}) {
  const utils = render(
    <ResizablePanel {...overrides}>
      <div>content</div>
    </ResizablePanel>,
  );
  const panel = utils.container.firstElementChild as HTMLElement;
  const handle = panel.querySelector('[class*="cursor-col-resize"]') as HTMLElement;
  return { utils, panel, handle };
}

function drag(handle: HTMLElement, fromX: number, toX: number) {
  fireEvent.mouseDown(handle, { clientX: fromX });
  fireEvent.mouseMove(document, { clientX: toX });
}

describe('ResizablePanel', () => {
  afterEach(cleanup);

  it('renders at the default width', () => {
    const { panel } = setup();
    expect(panel.style.width).toBe('240px');
  });

  it('widens a right-side panel when dragging the handle leftwards', () => {
    const { panel, handle } = setup();
    drag(handle, 300, 250);
    expect(panel.style.width).toBe('290px');
  });

  it('clamps to minWidth', () => {
    const { panel, handle } = setup({ minWidth: 200, maxWidth: 500 });
    drag(handle, 400, 10_000);
    expect(panel.style.width).toBe('200px');
  });

  it('clamps to maxWidth', () => {
    const { panel, handle } = setup({ maxWidth: 300 });
    drag(handle, 200, 0);
    expect(panel.style.width).toBe('300px');
  });

  it('widens a left-side panel when dragging the handle rightwards', () => {
    const { panel, handle } = setup({ side: 'left' });
    drag(handle, 200, 300);
    expect(panel.style.width).toBe('340px');
  });

  it('restores body cursor and user-select after mouseup', () => {
    const { handle } = setup();
    fireEvent.mouseDown(handle, { clientX: 300 });
    expect(document.body.style.cursor).toBe('col-resize');
    fireEvent.mouseUp(document);
    expect(document.body.style.cursor).toBe('');
    expect(document.body.style.userSelect).toBe('');
  });

  it('releases listeners and restores body styles when unmounted mid-drag', () => {
    const { utils, handle } = setup();
    fireEvent.mouseDown(handle, { clientX: 300 });
    utils.unmount();
    expect(document.body.style.cursor).toBe('');
    expect(document.body.style.userSelect).toBe('');
    // A stray mousemove after unmount must not throw or leak.
    expect(() => fireEvent.mouseMove(document, { clientX: 100 })).not.toThrow();
  });
});
