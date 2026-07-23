// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FileToolbar } from './FileToolbar';

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'sort.name': 'Name',
      'sort.date': 'Date',
      'sort.size': 'Size',
      'browse.selected': '{0} selected',
    })[key] ?? key,
  }),
}));

describe('FileToolbar', () => {
  it('keeps the ZIP command visible and disabled until an explicit selection exists', () => {
    const onDownloadSelected = vi.fn();
    render(
      <FileToolbar
        sort={{ sort: 'name', order: 'asc' }}
        onSortChange={vi.fn()}
        viewMode="grid"
        onViewModeChange={vi.fn()}
        selectedCount={0}
        onDownloadSelected={onDownloadSelected}
      />,
    );

    const download = screen.getByRole('button', { name: 'Download 0 selected items as ZIP' });
    expect((download as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(download);
    expect(onDownloadSelected).not.toHaveBeenCalled();
  });

  it('renders an active tag as a removable filter chip', () => {
    const onClearTag = vi.fn();
    render(
      <FileToolbar
        sort={{ sort: 'name', order: 'asc' }}
        onSortChange={vi.fn()}
        viewMode="grid"
        onViewModeChange={vi.fn()}
        selectedCount={1}
        onDownloadSelected={vi.fn()}
        activeTag="featured"
        onClearTag={onClearTag}
      />,
    );

    expect(screen.getByText('featured')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Clear tag filter: featured' }));
    expect(onClearTag).toHaveBeenCalledOnce();
  });
});
