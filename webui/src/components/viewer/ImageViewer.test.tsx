// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImageViewer } from './ImageViewer';

describe('ImageViewer', () => {
  afterEach(cleanup);
  it('fits the complete image to the canvas and allows zooming below fit scale', () => {
    render(<ImageViewer images={['square.png']} currentIndex={0} onClose={vi.fn()} />);

    const image = screen.getByAltText('Image 1');
    expect(image.className).toContain('object-contain');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    expect(image.style.transform).toContain('scale(0.5)');

    fireEvent.click(screen.getByRole('button', { name: 'Reset zoom' }));
    expect(image.style.transform).toContain('scale(1)');
  });

  it('allows wheel zooming below the fit scale', () => {
    render(<ImageViewer images={['portrait.png']} currentIndex={0} onClose={vi.fn()} />);

    fireEvent.wheel(screen.getByTestId('image-viewer-content'), { deltaY: 50, clientX: 100, clientY: 100 });
    expect(screen.getByAltText('Image 1').style.transform).toContain('scale(0.5)');
  });

  it('clamps zoom out at 25 percent and restores fit scale after navigation', () => {
    render(<ImageViewer images={['first.png', 'second.png']} currentIndex={0} onClose={vi.fn()} />);

    const zoomOut = screen.getByRole('button', { name: 'Zoom out' });
    fireEvent.click(zoomOut);
    fireEvent.click(zoomOut);
    fireEvent.click(zoomOut);
    expect(screen.getByAltText('Image 1').style.transform).toContain('scale(0.25)');

    fireEvent.click(screen.getByRole('button', { name: 'Next image' }));
    expect(screen.getByAltText('Image 2').style.transform).toContain('scale(1)');
  });

  it('resets zoom with 0 without closing and navigates with arrow keys inside the viewer', () => {
    const onClose = vi.fn();
    const onIndexChange = vi.fn();
    render(<ImageViewer images={['first.png', 'second.png']} currentIndex={0} onClose={onClose} onIndexChange={onIndexChange} />);

    const content = screen.getByTestId('image-viewer-content');
    fireEvent.wheel(content, { deltaY: -100 });
    expect(screen.getByAltText('Image 1').style.transform).not.toContain('scale(1)');

    fireEvent.keyDown(content, { key: '0' });
    expect(screen.getByAltText('Image 1').style.transform).toContain('scale(1)');
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(content, { key: 'ArrowRight' });
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });

  it('does not let keyboard events outside the viewer navigate images', () => {
    const onIndexChange = vi.fn();
    render(<><button>Outside</button><ImageViewer images={['first.png', 'second.png']} currentIndex={0} onClose={vi.fn()} onIndexChange={onIndexChange} /></>);

    fireEvent.keyDown(screen.getByRole('button', { name: 'Outside' }), { key: 'ArrowRight' });
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it('focuses viewer content so navigation and reset keys work immediately', () => {
    const onIndexChange = vi.fn();
    render(<ImageViewer images={['first.png', 'second.png']} currentIndex={0} onClose={vi.fn()} onIndexChange={onIndexChange} />);

    const content = screen.getByTestId('image-viewer-content');
    expect(document.activeElement).toBe(content);
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' });
    expect(onIndexChange).toHaveBeenCalledWith(1);
    fireEvent.keyDown(document.activeElement!, { key: '0' });
    expect(screen.getByAltText('Image 2').style.transform).toContain('scale(1)');
  });

  it('closes when Escape is pressed from the zoom toolbar', () => {
    const onClose = vi.fn();
    render(<ImageViewer images={['first.png']} currentIndex={0} onClose={onClose} />);

    const zoomIn = screen.getByRole('button', { name: 'Zoom in' });
    zoomIn.focus();
    fireEvent.keyDown(zoomIn, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledOnce();
  });

  it('cycles Tab from the last viewer control to the first dialog control', () => {
    render(<ImageViewer images={['first.png', 'second.png']} currentIndex={0} onClose={vi.fn()} />);

    const firstControl = screen.getByRole('button', { name: 'Zoom in' });
    const lastControl = screen.getByRole('button', { name: 'Next image' });
    lastControl.focus();
    fireEvent.keyDown(lastControl, { key: 'Tab' });

    expect(document.activeElement).toBe(firstControl);
  });

  it('synchronizes a later currentIndex change and resets zoom', () => {
    const view = render(<ImageViewer images={['first.png', 'second.png']} currentIndex={0} onClose={vi.fn()} />);
    const content = screen.getByTestId('image-viewer-content');
    fireEvent.wheel(content, { deltaY: -100 });
    expect(screen.getByAltText('Image 1').style.transform).not.toContain('scale(1)');

    view.rerender(<ImageViewer images={['first.png', 'second.png']} currentIndex={1} onClose={vi.fn()} />);
    expect(screen.getByAltText('Image 2').style.transform).toContain('scale(1)');
  });

  it('toggles touch zoom on double tap without closing', () => {
    const onClose = vi.fn();
    render(<ImageViewer images={['first.png']} currentIndex={0} onClose={onClose} />);
    const content = screen.getByTestId('image-viewer-content');

    const touchUp = (pointerId: number, clientX: number, clientY: number) => {
      const event = new Event('pointerup', { bubbles: true });
      Object.assign(event, { pointerId, pointerType: 'touch', clientX, clientY });
      fireEvent(content, event);
    };
    touchUp(1, 40, 40);
    touchUp(2, 42, 42);
    expect(screen.getByAltText('Image 1').style.transform).toContain('scale(2)');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('clears cancelled touch pointers so a remaining pointer cannot pinch zoom', () => {
    render(<ImageViewer images={['first.png']} currentIndex={0} onClose={vi.fn()} />);
    const content = screen.getByTestId('image-viewer-content');
    const pointerEvent = (type: string, pointerId: number, clientX: number, clientY: number) => {
      const event = new Event(type, { bubbles: true });
      Object.assign(event, { pointerId, pointerType: 'touch', clientX, clientY });
      fireEvent(content, event);
    };

    pointerEvent('pointerdown', 1, 0, 0);
    pointerEvent('pointerdown', 2, 100, 0);
    pointerEvent('pointercancel', 1, 0, 0);
    pointerEvent('pointermove', 2, 200, 0);

    expect(screen.getByAltText('Image 1').style.transform).toContain('scale(1)');
  });

  it('clears a scale-one pointer that is released outside before a later single-pointer move', () => {
    render(<ImageViewer images={['first.png']} currentIndex={0} onClose={vi.fn()} />);
    const content = screen.getByTestId('image-viewer-content');
    class TestPointerEvent extends MouseEvent {
      pointerId: number;
      pointerType: string;
      constructor(type: string, init: MouseEventInit & { pointerId: number; pointerType: string }) {
        super(type, init);
        this.pointerId = init.pointerId;
        this.pointerType = init.pointerType;
      }
    }
    const pointerEvent = (type: string, pointerId: number, clientX: number, clientY: number) => {
      return new TestPointerEvent(type, { bubbles: true, pointerId, pointerType: 'touch', clientX, clientY });
    };

    fireEvent(content, pointerEvent('pointerdown', 1, 0, 0));
    fireEvent(content, pointerEvent('lostpointercapture', 1, 0, 0));
    fireEvent(content, pointerEvent('pointerdown', 2, 100, 0));
    fireEvent(content, pointerEvent('pointermove', 2, 200, 0));

    expect(screen.getByAltText('Image 1').style.transform).toContain('scale(1)');
  });
});
