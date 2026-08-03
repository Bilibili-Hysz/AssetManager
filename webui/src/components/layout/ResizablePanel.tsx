import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react';

interface ResizablePanelProps {
  children: ReactNode;
  defaultWidth?: number;
  minWidth?: number;
  maxWidth?: number;
  side?: 'left' | 'right';
}

export function ResizablePanel({
  children,
  defaultWidth = 240,
  minWidth = 160,
  maxWidth = 400,
  side = 'right',
}: ResizablePanelProps) {
  const [width, setWidth] = useState(defaultWidth);
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);
  const moveHandlerRef = useRef<((e: MouseEvent) => void) | null>(null);
  const upHandlerRef = useRef<(() => void) | null>(null);

  const stopDrag = useCallback(() => {
    isDragging.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    if (moveHandlerRef.current) document.removeEventListener('mousemove', moveHandlerRef.current);
    if (upHandlerRef.current) document.removeEventListener('mouseup', upHandlerRef.current);
    moveHandlerRef.current = null;
    upHandlerRef.current = null;
  }, []);

  // Release listeners and restore body styles if the panel unmounts mid-drag.
  useEffect(() => stopDrag, [stopDrag]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (isDragging.current) return;
    isDragging.current = true;
    startX.current = e.clientX;
    startWidth.current = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = side === 'right' ? startX.current - e.clientX : e.clientX - startX.current;
      setWidth(Math.max(minWidth, Math.min(maxWidth, startWidth.current + delta)));
    };

    moveHandlerRef.current = handleMouseMove;
    upHandlerRef.current = stopDrag;
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', stopDrag);
  }, [width, side, minWidth, maxWidth, stopDrag]);

  return (
    <div className="relative flex-shrink-0" style={{ width }}>
      <div
        className={`absolute top-0 w-1 h-full cursor-col-resize z-10 hover:bg-brand-500/50 transition-colors ${
          side === 'left' ? 'right-0' : 'left-0'
        }`}
        onMouseDown={handleMouseDown}
      />
      {children}
    </div>
  );
}