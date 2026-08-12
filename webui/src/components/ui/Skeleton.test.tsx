// @vitest-environment jsdom
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardSkeleton, Skeleton } from './Skeleton';

describe('Skeleton', () => {
  it('renders one placeholder by default with the default class', () => {
    const { container } = render(<Skeleton />);
    const blocks = container.querySelectorAll('.skeleton');
    expect(blocks.length).toBe(1);
    expect(blocks[0]?.className).toContain('h-4 w-full');
  });

  it('renders the requested count with a custom class', () => {
    const { container } = render(<Skeleton count={3} className="h-8 w-1/2" />);
    const blocks = container.querySelectorAll('.skeleton');
    expect(blocks.length).toBe(3);
    expect(blocks[0]?.className).toContain('h-8 w-1/2');
  });
});

describe('CardSkeleton', () => {
  it('renders the card-shaped placeholder stack', () => {
    const { container } = render(<CardSkeleton />);
    expect(container.querySelectorAll('.skeleton').length).toBe(3);
  });
});
