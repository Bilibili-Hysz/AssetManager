// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DominantPaletteStrip } from './DominantPaletteStrip';

describe('DominantPaletteStrip', () => {
  afterEach(cleanup);

  it('renders nothing when colors array is empty', () => {
    render(<DominantPaletteStrip palette={{ colors: [] }} />);
    expect(screen.queryByTestId('dominant-palette-strip')).toBeNull();
  });

  it('renders 5 color swatches from palette', () => {
    const palette = {
      colors: ['#ff0000', '#00ff00', '#0000ff', '#ffffff', '#000000', '#ffff00'],
      dominant: '#ff0000',
    };

    render(<DominantPaletteStrip palette={palette} />);
    const strip = screen.getByTestId('dominant-palette-strip');
    expect(strip).toBeDefined();

    // Max 5 swatches rendered
    expect(screen.getByRole('button', { name: /色值 #ff0000/ })).toBeDefined();
    expect(screen.getByRole('button', { name: /色值 #000000/ })).toBeDefined();
    expect(screen.queryByRole('button', { name: /色值 #ffff00/ })).toBeNull();
  });

  it('copies hex to clipboard on click and triggers onSearchByTone', async () => {
    const onSearchByTone = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: { writeText },
    });

    render(
      <DominantPaletteStrip
        palette={['#5b7cf0', '#ffffff']}
        onSearchByTone={onSearchByTone}
      />,
    );

    const swatch = screen.getByRole('button', { name: /色值 #5b7cf0/ });
    fireEvent.click(swatch);
    expect(writeText).toHaveBeenCalledWith('#5B7CF0');

    const searchBtn = screen.getByRole('button', { name: /按色调检索 #5b7cf0/ });
    fireEvent.click(searchBtn);
    expect(onSearchByTone).toHaveBeenCalledWith('#5b7cf0');
  });
});
