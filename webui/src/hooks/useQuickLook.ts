import { useState, useCallback, useEffect, useRef } from 'react';
import type { BrowsableItem } from '../types/api';

interface UseQuickLookOptions {
  items: BrowsableItem[];
  selectedIndex: number;
  onNavigateIndex: (index: number) => void;
  onOpenDetail?: (item: BrowsableItem) => void;
}

export function useQuickLook({
  items,
  selectedIndex,
  onNavigateIndex,
  onOpenDetail,
}: UseQuickLookOptions) {
  const [isOpen, setIsOpen] = useState(false);
  const activeIndexRef = useRef(selectedIndex);
  activeIndexRef.current = selectedIndex;

  const open = useCallback(() => {
    if (items.length > 0) setIsOpen(true);
  }, [items.length]);

  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => {
    if (items.length === 0) return;
    setIsOpen(prev => !prev);
  }, [items.length]);

  const prev = useCallback(() => {
    if (items.length <= 1) return;
    const nextIndex = activeIndexRef.current > 0 ? activeIndexRef.current - 1 : items.length - 1;
    onNavigateIndex(nextIndex);
  }, [items.length, onNavigateIndex]);

  const next = useCallback(() => {
    if (items.length <= 1) return;
    const nextIndex = activeIndexRef.current < items.length - 1 ? activeIndexRef.current + 1 : 0;
    onNavigateIndex(nextIndex);
  }, [items.length, onNavigateIndex]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isInteractive =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        Boolean(target?.isContentEditable) ||
        (target instanceof Element && Boolean(target.closest('button, a')));
      if (isInteractive) return;

      if (e.code === 'Space') {
        if (items.length > 0) {
          e.preventDefault();
          toggle();
        }
        return;
      }

      if (!isOpen) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        prev();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        next();
      } else if (e.key === 'Enter') {
        const item = items[activeIndexRef.current];
        if (item && onOpenDetail) {
          e.preventDefault();
          close();
          onOpenDetail(item);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, toggle, close, prev, next, items, onOpenDetail]);

  return {
    isOpen,
    open,
    close,
    prev,
    next,
    currentItem: items[selectedIndex] ?? null,
  };
}
