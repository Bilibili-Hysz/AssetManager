// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { LayeredPreview } from './LayeredPreview';

describe('LayeredPreview', () => {
  afterEach(cleanup);

  it('renders one cover with two backing layers and falls back after image error', () => {
    render(<LayeredPreview src="/api/thumbnails/folder/cover.png" alt="Assets" isDir size="grid" />);

    const image = screen.getByRole('img', { name: 'Assets' });
    expect(image.getAttribute('src')).toBe('/api/thumbnails/folder/cover.png');
    expect(screen.getAllByTestId('layered-preview-back')).toHaveLength(2);

    fireEvent.error(image);

    expect(screen.queryByRole('img', { name: 'Assets' })).toBeNull();
    expect(screen.getByTestId('layered-preview-folder')).toBeDefined();
  });

  it('uses a stable list size and file fallback when src is absent', () => {
    render(<LayeredPreview alt="Readme" isDir={false} size="list" />);

    expect(screen.getByTestId('layered-preview-file')).toBeDefined();
    expect(screen.getByTestId('layered-preview').getAttribute('data-size')).toBe('list');
  });
});
