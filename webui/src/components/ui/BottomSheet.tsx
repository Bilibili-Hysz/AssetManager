import { useState, useRef, useCallback } from 'react';

export type SnapPoint = 'peek' | 'half' | 'full';

interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  initialSnap?: SnapPoint;
}

const SNAP_RATIOS: Record<SnapPoint, number> = {
  peek: 0.35,  // 35% height
  half: 0.65,  // 65% height
  full: 0.94,  // 94% height
};

export function BottomSheet({
  isOpen,
  onClose,
  title,
  children,
  initialSnap = 'half',
}: BottomSheetProps) {
  const [currentSnap, setCurrentSnap] = useState<SnapPoint>(initialSnap);
  const [dragOffset, setDragOffset] = useState<number>(0);
  const [isDragging, setIsDragging] = useState(false);

  const sheetRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const startYRef = useRef(0);
  const currentYRef = useRef(0);
  const lastTimeRef = useRef(0);
  const velocityRef = useRef(0);

  const windowHeight = typeof window !== 'undefined' ? window.innerHeight : 800;
  const currentHeight = windowHeight * SNAP_RATIOS[currentSnap];

  const snapTo = useCallback((snap: SnapPoint) => {
    setCurrentSnap(snap);
    setDragOffset(0);
  }, []);

  const handleTouchStart = (e: React.TouchEvent) => {
    const touch = e.touches[0];
    if (!touch) return;

    // When scrolling inside content that hasn't scrolled to top, do not drag sheet
    const scrollContainer = scrollContainerRef.current;
    if (scrollContainer && scrollContainer.scrollTop > 0) {
      return;
    }

    startYRef.current = touch.clientY;
    currentYRef.current = touch.clientY;
    lastTimeRef.current = Date.now();
    velocityRef.current = 0;
    setIsDragging(true);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (!isDragging) return;
    const touch = e.touches[0];
    if (!touch) return;

    const deltaY = touch.clientY - startYRef.current;
    const now = Date.now();
    const dt = now - lastTimeRef.current;
    if (dt > 0) {
      velocityRef.current = (touch.clientY - currentYRef.current) / dt;
    }
    currentYRef.current = touch.clientY;
    lastTimeRef.current = now;

    // Upward drag gets rubberband damping
    if (deltaY < 0) {
      setDragOffset(deltaY * 0.25);
    } else {
      setDragOffset(deltaY);
    }
  };

  const handleTouchEnd = () => {
    if (!isDragging) return;
    setIsDragging(false);

    const deltaY = dragOffset;
    const velocity = velocityRef.current;

    // Rapid swipe down triggers close or snap down
    if (velocity > 0.6 || deltaY > currentHeight * 0.4) {
      if (currentSnap === 'full') {
        snapTo('half');
      } else if (currentSnap === 'half') {
        snapTo('peek');
      } else {
        onClose();
      }
      return;
    }

    // Rapid swipe up triggers expand
    if (velocity < -0.6) {
      if (currentSnap === 'peek') snapTo('half');
      else snapTo('full');
      return;
    }

    // Snap to nearest target point
    const effectiveHeight = currentHeight - deltaY;
    if (effectiveHeight < windowHeight * 0.18) {
      onClose();
      return;
    }

    const distances = (Object.keys(SNAP_RATIOS) as SnapPoint[]).map(snap => ({
      snap,
      dist: Math.abs(windowHeight * SNAP_RATIOS[snap] - effectiveHeight),
    }));
    distances.sort((a, b) => a.dist - b.dist);
    snapTo(distances[0]?.snap ?? 'half');
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[var(--z-drawer,60)] flex flex-col justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet Container */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Drawer'}
        data-testid="bottom-sheet"
        className="relative w-full rounded-t-[20px] bg-[var(--color-surface)] border-t border-[var(--color-border)] shadow-2xl overflow-hidden flex flex-col"
        style={{
          height: `${Math.max(120, currentHeight - dragOffset)}px`,
          transition: isDragging ? 'none' : 'height 320ms cubic-bezier(0.32, 0.72, 0, 1)',
          paddingBottom: 'env(safe-area-inset-bottom, 16px)',
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Grabber Handle */}
        <div
          data-testid="bottom-sheet-grabber"
          className="flex-shrink-0 flex items-center justify-center pt-2.5 pb-2 cursor-grab active:cursor-grabbing touch-none"
        >
          <div className="h-1.5 w-10 rounded-full bg-slate-500/50 hover:bg-slate-400/80 transition-colors" />
        </div>

        {/* Scrollable Content Container */}
        <div
          ref={scrollContainerRef}
          className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 pb-4"
        >
          {children}
        </div>
      </div>
    </div>
  );
}
