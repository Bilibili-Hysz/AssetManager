// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InfoPanel } from './InfoPanel';

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ api: { buildUrl: (path: string) => '/api/' + path } }),
}));

describe('InfoPanel', () => {
  afterEach(cleanup);
  it('renders only absolute HTTP and HTTPS metadata links', () => {
    render(<InfoPanel metadata={{ path: 'asset.txt', tags: [], notes: '', urls: [
      'https://example.com/reference',
      'http://example.com/source',
      'https:',
      'javascript:alert(1)',
      'file:///private/path',
    ] }} />);

    expect(screen.getAllByRole('link').map(link => link.getAttribute('href'))).toEqual([
      'https://example.com/reference',
      'http://example.com/source',
    ]);
  });

  it('emits the selected tag through the semantic filter callback', () => {
    const onTagFilter = vi.fn();
    render(<InfoPanel
      metadata={{ path: 'asset.txt', tags: ['featured'], notes: '', urls: [] }}
      selected={{ name: 'asset.txt', path: 'asset.txt', type: 'file', size: 12, size_fmt: '12 B', modified: 0, extension: '.txt', category: 'document' }}
      onTagFilter={onTagFilter}
    />);

    fireEvent.click(screen.getByRole('button', { name: 'featured' }));
    expect(onTagFilter).toHaveBeenCalledWith('featured');
  });

  it('shows the trusted project modified time in the technical details', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'asset.txt', path: 'asset.txt', type: 'file', size: 12, size_fmt: '12 B', modified: 1_700_000_000, extension: '.txt', category: 'document' }}
    />);

    expect(screen.getByText('Modified')).toBeDefined();
    expect(screen.getByText(new Date(1_700_000_000 * 1000).toLocaleString())).toBeDefined();
  });

  it('hides technical fields that tag search results do not provide', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'tagged.png', path: 'tagged.png', type: 'file', extension: '.png', category: 'image' }}
    />);

    expect(screen.queryByText('Size')).toBeNull();
    expect(screen.queryByText('Modified')).toBeNull();
    expect(screen.queryByText(/1970/)).toBeNull();
  });

  it('places actions after the preview, metadata, and all inspection details', () => {
    render(<InfoPanel
      metadata={{ path: 'asset.png', tags: ['featured'], notes: 'Inspection note', urls: ['https://example.com/reference'] }}
      selected={{ name: 'asset.png', path: 'asset.png', type: 'file', size: 12, size_fmt: '12 B', modified: 1_700_000_000, extension: '.png', category: 'image', thumbnail_url: 'https://example.com/preview.png' }}
      onDownload={vi.fn()}
      onShare={vi.fn()}
      onClose={vi.fn()}
    />);

    const preview = screen.getByAltText('asset.png preview');
    const tag = screen.getByRole('button', { name: 'featured' });
    const notes = screen.getByText('Inspection note');
    const url = screen.getByRole('link', { name: 'https://example.com/reference' });
    const technical = screen.getByText('Path').parentElement!;
    const download = screen.getByRole('button', { name: 'Download' });
    const share = screen.getByRole('button', { name: 'Share' });

    const ordered: HTMLElement[] = [preview, tag, notes, url, technical, download, share];
    for (let index = 0; index < ordered.length - 1; index += 1) {
      expect(ordered[index]!.compareDocumentPosition(ordered[index + 1]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(download.closest('header')).toBeNull();
  });

  it('opens the selected image in the high-resolution viewer and restores focus', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'hero.png', path: 'characters/hero.png', type: 'file', extension: '.png', category: 'images', thumbnail_url: '/api/thumbnails/characters/hero.png?size=512' }}
    />);

    const trigger = screen.getByRole('button', { name: 'Open hero.png preview' });
    const preview = screen.getByAltText('hero.png preview');
    expect(trigger.className).toContain('aspect-video');
    expect(preview.className).toContain('object-contain');
    expect(preview.className).not.toContain('object-cover');
    fireEvent.click(trigger);

    expect(screen.getByRole('dialog', { name: 'Image viewer' })).toBeDefined();
    expect(screen.getByRole('img', { name: 'Image 1' }).getAttribute('src')).toBe(
      '/api/thumbnails/characters/hero.png?size=2048',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Close image viewer' }));
    expect(screen.queryByRole('dialog', { name: 'Image viewer' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('renders the selected project cover and opens its legacy image gallery', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'Project Alpha', path: 'projects/alpha', type: 'dir', extension: '', category: 'folder', is_project: true }}
      projectDetail={{
        name: 'Project Alpha',
        path: 'projects/alpha',
        tags: [],
        notes: '',
        urls: [],
        total_size: 30,
        total_size_fmt: '30 B',
        file_count: 2,
        files: [],
        images: [
          { name: 'first.png', url: '/api/thumbnails/projects/alpha/first.png?size=1920', thumb_url: '/api/thumbnails/projects/alpha/first.png?size=512' },
          { name: 'cover.png', url: '/api/thumbnails/projects/alpha/cover.png?size=1920', thumb_url: '/api/thumbnails/projects/alpha/cover.png?size=512' },
        ],
        thumbnail_url: '/api/thumbnails/projects/alpha/cover.png?size=512',
        modified: 1_700_000_000,
        download_url: '/api/download/projects/alpha',
      }}
    />);

    const cover = screen.getByAltText('Project Alpha preview');
    expect(cover.getAttribute('src')).toBe('/api/thumbnails/projects/alpha/cover.png?size=512');
    fireEvent.click(screen.getByRole('button', { name: 'Open Project Alpha preview' }));
    expect(screen.getByRole('img', { name: 'Image 2' }).getAttribute('src')).toBe(
      '/api/thumbnails/projects/alpha/cover.png?size=1920',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Previous image' }));
    expect(screen.getByRole('img', { name: 'Image 1' }).getAttribute('src')).toBe(
      '/api/thumbnails/projects/alpha/first.png?size=1920',
    );
  });

  it('renders and opens a project cover when the project gallery is empty', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'Nested Project', path: 'projects/nested', type: 'dir', extension: '', category: 'folder', is_project: true }}
      projectDetail={{
        name: 'Nested Project', path: 'projects/nested', tags: [], notes: '', urls: [],
        total_size: 1, total_size_fmt: '1 B', file_count: 0, files: [], images: [],
        thumbnail_url: '/api/thumbnails/projects/nested/cover.png', modified: 1,
        download_url: '/api/download/projects/nested',
      }}
    />);

    expect(screen.getByAltText('Nested Project preview').getAttribute('src')).toBe(
      '/api/thumbnails/projects/nested/cover.png',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Open Nested Project preview' }));
    expect(screen.getByRole('img', { name: 'Image 1' }).getAttribute('src')).toBe(
      '/api/thumbnails/projects/nested/cover.png',
    );
  });

  it('renders a preview from the selected image path without a thumbnail URL', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'hero.png', path: 'characters/hero.png', type: 'file', extension: '.png', category: 'images' }}
    />);

    expect(screen.getByAltText('hero.png preview').getAttribute('src')).toBe(
      '/api/thumbnails/characters/hero.png?size=512',
    );
  });

  it('shows a loading status until the preview image finishes loading', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'hero.png', path: 'characters/hero.png', type: 'file', extension: '.png', category: 'images' }}
    />);

    expect(screen.getByRole('status', { name: 'Loading preview' })).toBeDefined();
  });

  it('starts the image preview while metadata details are still loading', () => {
    render(<InfoPanel
      metadata={null}
      loading
      selected={{ name: 'hero.png', path: 'characters/hero.png', type: 'file', extension: '.png', category: 'images' }}
    />);

    expect(screen.getByRole('button', { name: 'Open hero.png preview' })).toBeDefined();
    expect(screen.getByAltText('hero.png preview').getAttribute('src')).toBe(
      '/api/thumbnails/characters/hero.png?size=512',
    );
  });

  it('shows a visible preview error when the thumbnail request fails', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'hero.png', path: 'hero.png', type: 'file', extension: '.png', category: 'images' }}
    />);

    fireEvent.error(screen.getByAltText('hero.png preview'));

    expect(screen.getByText('Preview unavailable')).toBeDefined();
  });

  it.each(['.bmp', '.tiff', '.ico', '.svg'])('shows a preview for %s images', extension => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: `asset${extension}`, path: `asset${extension}`, type: 'file', extension, category: 'images', thumbnail_url: `/api/thumbnails/asset${extension}` }}
    />);

    expect(screen.getByRole('button', { name: `Open asset${extension} preview` })).toBeDefined();
    cleanup();
  });

  it('does not show a preview trigger for non-image assets', () => {
    render(<InfoPanel
      metadata={null}
      selected={{ name: 'notes.txt', path: 'notes.txt', type: 'file', extension: '.txt', category: 'document', thumbnail_url: '/api/thumbnails/notes.txt' }}
    />);

    expect(screen.queryByRole('button', { name: 'Open notes.txt preview' })).toBeNull();
  });
  it('delegates notes editing to the save callback', async () => {
    const onNotesSave = vi.fn().mockResolvedValue(true);
    render(<InfoPanel
      metadata={{ path: 'asset.txt', tags: [], notes: '', urls: [] }}
      selected={{ name: 'asset.txt', path: 'asset.txt', type: 'file', extension: '.txt', category: 'document' }}
      onNotesSave={onNotesSave}
    />);

    fireEvent.click(screen.getByRole('button', { name: /Edit|编辑|編集/ }));
    const editor = screen.getByRole('textbox', { name: /Notes|备注|メモ/ });
    fireEvent.change(editor, { target: { value: 'new note' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save|保存/ }));
    });

    expect(onNotesSave).toHaveBeenCalledWith('asset.txt', 'new note');
  });

  it('delegates tag add and remove mutations while retaining the filter action', async () => {
    const onTagFilter = vi.fn();
    const onTagAdd = vi.fn().mockResolvedValue(true);
    const onTagRemove = vi.fn().mockResolvedValue(true);
    render(<InfoPanel
      metadata={{ path: 'asset.txt', tags: ['featured'], notes: '', urls: [] }}
      selected={{ name: 'asset.txt', path: 'asset.txt', type: 'file', extension: '.txt', category: 'document' }}
      onTagFilter={onTagFilter}
      onTagAdd={onTagAdd}
      onTagRemove={onTagRemove}
    />);

    fireEvent.click(screen.getByRole('button', { name: 'featured' }));
    expect(onTagFilter).toHaveBeenCalledWith('featured');

    const input = screen.getByRole('textbox', { name: /Add tag|添加标签|タグを追加/ });
    fireEvent.change(input, { target: { value: 'new-tag' } });
    await act(async () => {
      fireEvent.submit(input.closest('form')!);
    });
    expect(onTagAdd).toHaveBeenCalledWith('new-tag');

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Remove tag|移除标签|タグ .*削除/ }));
    });
    expect(onTagRemove).toHaveBeenCalledWith('featured');
  });

});
