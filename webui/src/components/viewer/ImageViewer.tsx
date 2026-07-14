import { useState, useCallback, useRef } from 'react';
import { X, ZoomIn, ZoomOut, RotateCcw, ChevronLeft, ChevronRight } from 'lucide-react';
import { useDialogFocus } from '../../hooks/useDialogFocus';

interface ImageViewerProps {
  images: string[];
  currentIndex: number;
  onClose: () => void;
  onIndexChange?: (index: number) => void;
}

export function ImageViewer({ images, currentIndex, onClose, onIndexChange }: ImageViewerProps) {
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [index, setIndex] = useState(currentIndex);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startY: 0, startPosX: 0, startPosY: 0 });
  const dialogRef = useDialogFocus(true, onClose);

  const prev = () => {
    const i = index > 0 ? index - 1 : images.length - 1;
    setIndex(i); setScale(1); setPosition({ x: 0, y: 0 });
    onIndexChange?.(i);
  };

  const next = () => {
    const i = index < images.length - 1 ? index + 1 : 0;
    setIndex(i); setScale(1); setPosition({ x: 0, y: 0 });
    onIndexChange?.(i);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowLeft') prev();
    if (event.key === 'ArrowRight') next();
  };

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale(s => Math.max(0.5, Math.min(5, s - e.deltaY * 0.01)));
  }, []);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (scale <= 1) return;
    setIsDragging(true);
    dragRef.current = { startX: e.clientX, startY: e.clientY, startPosX: position.x, startPosY: position.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPosition({
      x: dragRef.current.startPosX + (e.clientX - dragRef.current.startX),
      y: dragRef.current.startPosY + (e.clientY - dragRef.current.startY),
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label="Image viewer"
      tabIndex={-1}
      className="fixed inset-0 z-50 bg-black/95 flex flex-col"
      onKeyDown={handleKeyDown}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <div className="flex items-center justify-between px-4 py-3 bg-black/50">
        <span className="text-sm text-slate-400">{index + 1} / {images.length}</span>
        <div className="flex items-center gap-3">
          <button aria-label="Zoom in" onClick={() => setScale(s => Math.min(5, s + 0.5))} className="text-white/70 hover:text-white"><ZoomIn size={20} /></button>
          <button aria-label="Zoom out" onClick={() => setScale(s => Math.max(0.5, s - 0.5))} className="text-white/70 hover:text-white"><ZoomOut size={20} /></button>
          <button aria-label="Reset zoom" onClick={() => { setScale(1); setPosition({ x: 0, y: 0 }); }} className="text-white/70 hover:text-white"><RotateCcw size={20} /></button>
          <button aria-label="Close image viewer" onClick={onClose} className="text-white/70 hover:text-white"><X size={24} /></button>
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center relative overflow-hidden">
        {images.length > 1 && (
          <button aria-label="Previous image" onClick={prev} className="absolute left-4 z-10 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white">
            <ChevronLeft size={28} />
          </button>
        )}
        <img
          src={images[index]}
          alt={`Image ${index + 1}`}
          className="max-w-full max-h-full transition-transform duration-100 select-none"
          style={{
            transform: `scale(${scale}) translate(${position.x / scale}px, ${position.y / scale}px)`,
            cursor: scale > 1 ? 'grab' : 'default',
          }}
          draggable={false}
        />
        {images.length > 1 && (
          <button aria-label="Next image" onClick={next} className="absolute right-4 z-10 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white">
            <ChevronRight size={28} />
          </button>
        )}
      </div>
    </div>
  );
}
