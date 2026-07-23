// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InfoPanel } from './InfoPanel';

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
});
