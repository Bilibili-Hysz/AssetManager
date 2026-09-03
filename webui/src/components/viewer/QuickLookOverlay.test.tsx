// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QuickLookOverlay } from './QuickLookOverlay';
import type { BrowsableItem } from '../../types/api';

const mockImageItem: BrowsableItem = {
  name: 'photo.png',
  path: 'projects/photo.png',
  type: 'file',
  extension: '.png',
  category: 'image',
  size_fmt: '2.4 MB',
};

const mockVideoItem: BrowsableItem = {
  name: 'clip.mp4',
  path: 'projects/clip.mp4',
  type: 'file',
  extension: '.mp4',
  category: 'video',
  size_fmt: '14.2 MB',
};

describe('QuickLookOverlay', () => {
  afterEach(cleanup);

  it('does not render when isOpen is false', () => {
    render(
      <QuickLookOverlay
        item={mockImageItem}
        currentIndex={0}
        totalCount={1}
        isOpen={false}
        onClose={vi.fn()}
        onNext={vi.fn()}
        onPrev={vi.fn()}
        onOpenFullDetail={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('quicklook-overlay')).toBeNull();
  });

  it('renders image item details and responds to actions', () => {
    const onClose = vi.fn();
    const onNext = vi.fn();
    const onPrev = vi.fn();
    const onOpenFullDetail = vi.fn();
    const onDownload = vi.fn();

    render(
      <QuickLookOverlay
        item={mockImageItem}
        currentIndex={0}
        totalCount={3}
        isOpen={true}
        thumbnailPlaceholder="/thumb.png"
        originalMediaUrl="/full.png"
        onClose={onClose}
        onNext={onNext}
        onPrev={onPrev}
        onOpenFullDetail={onOpenFullDetail}
        onDownload={onDownload}
      />,
    );

    expect(screen.getByTestId('quicklook-overlay')).toBeDefined();
    expect(screen.getByText('photo.png')).toBeDefined();
    expect(screen.getByText('2.4 MB')).toBeDefined();
    expect(screen.getByText('1 / 3')).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: '下一张' }));
    expect(onNext).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '上一张' }));
    expect(onPrev).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '打开完整详情页' }));
    expect(onOpenFullDetail).toHaveBeenCalledWith(mockImageItem);

    fireEvent.click(screen.getByRole('button', { name: '下载资产' }));
    expect(onDownload).toHaveBeenCalledWith(mockImageItem);

    fireEvent.click(screen.getByRole('button', { name: '关闭即览' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders video element for video category', () => {
    render(
      <QuickLookOverlay
        item={mockVideoItem}
        currentIndex={1}
        totalCount={2}
        isOpen={true}
        originalMediaUrl="/clip.mp4"
        onClose={vi.fn()}
        onNext={vi.fn()}
        onPrev={vi.fn()}
        onOpenFullDetail={vi.fn()}
        onDownload={vi.fn()}
      />,
    );

    expect(screen.getByText('clip.mp4')).toBeDefined();
    expect(screen.getByRole('button', { name: '取消静音' })).toBeDefined();
  });
});
