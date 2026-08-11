// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SellerGalleryEditor from './SellerGalleryEditor';

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: Array<string | number>) => {
      const value = ({
        'seller.gallery_paths': 'Gallery paths',
        'seller.gallery_cover': 'Cover',
        'seller.gallery': 'Gallery',
        'seller.cover_path': 'Cover path',
        'seller.gallery_image_path': 'Gallery image path {0}',
        'seller.new_gallery_image_path': 'New gallery image path',
        'seller.gallery_paths_note': 'Cover and gallery paths are managed separately.',
        'seller.gallery_path_required': '路径不能为空。',
        'seller.gallery_path_relative': '请输入资源库内的相对图片路径。',
        'seller.gallery_path_duplicate_cover': '不能与 cover 路径重复。',
        'seller.gallery_path_duplicate': '路径重复，请使用不同的图片路径。',
        'seller.gallery_path_duplicate_item': '路径重复，请删除重复项。',
        'seller.gallery_preview': 'Gallery images',
        'seller.move_gallery_image_up': 'Move gallery image {0} up',
        'seller.move_gallery_image_down': 'Move gallery image {0} down',
        'seller.delete_gallery_image': 'Delete gallery image {0}',
        'seller.gallery_paths_help': 'Manage cover and gallery paths.',
        'seller.gallery_paths_placeholder': 'Relative image path',
        'info.path': 'Path',
        'info.add_tag': 'Add',
        'action.delete': 'Delete',
        'landing.previews_unavailable': 'Preview unavailable',
      }[key] ?? key);
      return args.reduce((result, arg, index) => String(result).replace(`{${index}}`, String(arg)), String(value));
    },
  }),
}));

const buildUrl = vi.fn((path: string) => `/api/${path}`);

function renderEditor(overrides: Partial<React.ComponentProps<typeof SellerGalleryEditor>> = {}) {
  const onChange = overrides.onChange ?? vi.fn();
  const props = {
    coverPath: 'assets/cover.png',
    galleryPaths: ['assets/detail-1.png', 'assets/detail-2.png'],
    buildUrl,
    onChange,
    ...overrides,
  };
  return { onChange, ...render(<SellerGalleryEditor {...props} />) };
}

afterEach(() => {
  cleanup();
  buildUrl.mockClear();
});

describe('SellerGalleryEditor', () => {
  it('emits cover and gallery edits through onChange', () => {
    const { onChange } = renderEditor();

    fireEvent.change(screen.getByRole('textbox', { name: 'Cover path' }), {
      target: { value: 'assets/new-cover.jpg' },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/new-cover.jpg',
      galleryPaths: ['assets/detail-1.png', 'assets/detail-2.png'],
    });

    fireEvent.change(screen.getByRole('textbox', { name: 'Gallery image path 2' }), {
      target: { value: 'assets/new-detail.webp' },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/new-cover.jpg',
      galleryPaths: ['assets/detail-1.png', 'assets/new-detail.webp'],
    });
  });

  it('rejects non-relative and duplicate paths', () => {
    const { onChange } = renderEditor({ coverPath: 'assets/cover.png', galleryPaths: ['assets/detail.png'] });
    const coverInput = screen.getByRole('textbox', { name: 'Cover path' });
    const galleryInput = screen.getByRole('textbox', { name: 'Gallery image path 1' });
    const newInput = screen.getByRole('textbox', { name: 'New gallery image path' });

    fireEvent.change(coverInput, { target: { value: '/absolute/cover.png' } });
    expect(screen.getAllByText('请输入资源库内的相对图片路径。').length).toBeGreaterThan(0);
    expect(onChange).toHaveBeenLastCalledWith({ coverPath: '/absolute/cover.png', galleryPaths: ['assets/detail.png'] });

    fireEvent.change(galleryInput, { target: { value: 'assets/../outside.png' } });
    expect(screen.getAllByText('请输入资源库内的相对图片路径。').length).toBeGreaterThan(0);

    fireEvent.change(screen.getByRole('textbox', { name: 'Cover path' }), { target: { value: 'assets/cover.png' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Gallery image path 1' }), { target: { value: 'assets/cover.png' } });
    const currentGalleryInput = screen.getByRole('textbox', { name: 'Gallery image path 1' });
    expect(currentGalleryInput.getAttribute('aria-invalid')).toBe('true');

    fireEvent.change(newInput, { target: { value: 'assets/cover.png' } });
    expect(screen.getByText('路径重复，请使用不同的图片路径。')).toBeDefined();
    expect((screen.getByRole('button', { name: 'Add' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('adds with normalized paths and removes gallery items', () => {
    const { onChange } = renderEditor({ galleryPaths: [] });
    const newInput = screen.getByRole('textbox', { name: 'New gallery image path' });

    fireEvent.change(newInput, { target: { value: '  assets\\detail.png  ' } });
    fireEvent.keyDown(newInput, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/cover.png',
      galleryPaths: ['assets/detail.png'],
    });
    expect((newInput as HTMLInputElement).value).toBe('');

    fireEvent.click(screen.getByRole('button', { name: 'Delete gallery image 1' }));
    expect(onChange).toHaveBeenLastCalledWith({ coverPath: 'assets/cover.png', galleryPaths: [] });
    expect(screen.queryByRole('textbox', { name: 'Gallery image path 1' })).toBeNull();
  });

  it('reorders items with buttons and ArrowUp/ArrowDown, and deletes on Delete', () => {
    const { onChange } = renderEditor();
    const listItems = screen.getAllByRole('listitem');

    fireEvent.click(screen.getByRole('button', { name: 'Move gallery image 2 up' }));
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/cover.png',
      galleryPaths: ['assets/detail-2.png', 'assets/detail-1.png'],
    });

    fireEvent.keyDown(screen.getAllByRole('listitem')[0]!, { key: 'ArrowDown' });
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/cover.png',
      galleryPaths: ['assets/detail-1.png', 'assets/detail-2.png'],
    });

    fireEvent.keyDown(screen.getAllByRole('listitem')[1]!, { key: 'ArrowUp' });
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/cover.png',
      galleryPaths: ['assets/detail-2.png', 'assets/detail-1.png'],
    });

    fireEvent.keyDown(screen.getAllByRole('listitem')[1]!, { key: 'Delete' });
    expect(onChange).toHaveBeenLastCalledWith({
      coverPath: 'assets/cover.png',
      galleryPaths: ['assets/detail-2.png'],
    });
    expect(listItems).toHaveLength(2);
  });

  it('builds image preview URLs and shows the fallback after preview failure', () => {
    renderEditor({ coverPath: 'assets/cover.png', galleryPaths: ['assets/detail.png'] });

    const coverPreview = screen.getByRole('img', { name: 'Cover: assets/cover.png' });
    expect(coverPreview.getAttribute('src')).toBe('/api/thumbnails/assets%2Fcover.png?size=256');
    expect(buildUrl).toHaveBeenCalledWith('thumbnails/assets%2Fcover.png?size=256');

    fireEvent.error(coverPreview);
    expect(screen.getByText('Preview unavailable')).toBeDefined();

    fireEvent.change(screen.getByRole('textbox', { name: 'Cover path' }), { target: { value: '/invalid.png' } });
    expect(screen.getByLabelText('Cover preview unavailable')).toBeDefined();
  });
});








