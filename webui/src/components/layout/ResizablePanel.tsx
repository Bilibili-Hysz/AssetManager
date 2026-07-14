import { useState, useRef, useCallback, type ReactNode } from 'react';

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

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
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

    const handleMouseUp = () => {
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [width, side, minWidth, maxWidth]);

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