// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FileToolbar } from './FileToolbar';

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: (string | number)[]) => ({
      'sort.name': 'Name',
      'sort.date': 'Date',
      'sort.size': 'Size',
      'browse.selected': '{0} selected',
      'browse.clear_tag_named': 'Clear tag filter: {0}',
      'browse.download_selected_zip': 'Download {0} selected items as ZIP',
      'browse.downloading_zip': 'Downloading ZIP...',
    })[key]?.replace('{0}', String(args[0])) ?? key,
  }),
}));

function baseProps(
  overrides: Partial<Parameters<typeof FileToolbar>[0]> = {},
): Parameters<typeof FileToolbar>[0] {
  return {
    sort: { sort: 'name', order: 'asc' },
    onSortChange: vi.fn(),
    viewMode: 'grid',
    onViewModeChange: vi.fn(),
    selectedCount: 0,
    onDownloadSelected: vi.fn(),
    ...overrides,
  };
}

describe('FileToolbar', () => {
  afterEach(() => cleanup());

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

  it('changes the sort key and toggles the order', () => {
    const onSortChange = vi.fn();
    render(
      <FileToolbar
        {...baseProps({ selectedCount: 1, onSortChange })}
      />,
    );

    fireEvent.change(screen.getByRole('combobox', { name: 'sort.by' }), { target: { value: 'date' } });
    expect(onSortChange).toHaveBeenCalledWith({ sort: 'date', order: 'asc' });
    fireEvent.click(screen.getByRole('button', { name: 'sort.desc' }));
    expect(onSortChange).toHaveBeenCalledWith({ sort: 'name', order: 'desc' });
  });

  it('switches the view mode', () => {
    const onViewModeChange = vi.fn();
    render(
      <FileToolbar
        {...baseProps({ selectedCount: 1, onViewModeChange })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'view.masonry' }));
    expect(onViewModeChange).toHaveBeenCalledWith('masonry');
    fireEvent.click(screen.getByRole('button', { name: 'view.list' }));
    expect(onViewModeChange).toHaveBeenCalledWith('list');
  });

  it('disables the ZIP command while a download is in flight', () => {
    render(
      <FileToolbar
        {...baseProps({ selectedCount: 2, isDownloadInFlight: true })}
      />,
    );
    const download = screen.getByRole('button', { name: 'Download 2 selected items as ZIP' });
    expect((download as HTMLButtonElement).disabled).toBe(true);
  });

  it('toggles selection mode when provided', () => {
    const onSelectModeToggle = vi.fn();
    render(
      <FileToolbar
        {...baseProps({ selectedCount: 1, selectMode: false, onSelectModeToggle })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'browse.select' }));
    expect(onSelectModeToggle).toHaveBeenCalledTimes(1);
  });
});

