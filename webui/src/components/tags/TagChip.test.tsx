// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TagChip } from './TagChip';

describe('TagChip', () => {
  afterEach(cleanup);

  it('renders the tag name', () => {
    render(<TagChip name="hello" />);
    expect(screen.getByText('hello')).toBeDefined();
  });

  it('renders the count when provided', () => {
    render(<TagChip name="project" count={5} />);
    expect(screen.getByText('(5)')).toBeDefined();
  });

  it('omits the count when not provided', () => {
    render(<TagChip name="project" />);
    expect(screen.queryByText(/^\(\d+\)$/)).toBeNull();
  });

  it('calls onClick when the chip is clicked', () => {
    const onClick = vi.fn();
    render(<TagChip name="tag" onClick={onClick} />);
    fireEvent.click(screen.getByText('tag'));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('prevents the remove button click from bubbling to the chip onClick', () => {
    const onClick = vi.fn();
    const onRemove = vi.fn();
    render(<TagChip name="tag" onClick={onClick} onRemove={onRemove} />);
    const buttons = screen.getAllByRole('button');
    fireEvent.click(buttons[buttons.length - 1]!);  // remove button
    expect(onRemove).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it('applies the cursor-pointer class when onClick is provided', () => {
    render(<TagChip name="tag" onClick={vi.fn()} />);
    expect(screen.getByText('tag').className).toContain('cursor-pointer');
  });

  it('does not apply cursor-pointer when onClick is absent', () => {
    render(<TagChip name="tag" />);
    expect(screen.getByText('tag').className).not.toContain('cursor-pointer');
  });
});
