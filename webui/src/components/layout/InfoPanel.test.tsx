// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { InfoPanel } from './InfoPanel';

describe('InfoPanel', () => {
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
});
