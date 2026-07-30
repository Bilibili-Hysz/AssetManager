// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectList } from './ProjectList';
import { SINGLE_CLICK_DELAY_MS } from './ProjectCard';

let testLang = 'en';
const messages: Record<string, Record<string, string>> = {
  en: { 'sort.name': 'Name', 'sort.size': 'Size', 'info.modified': 'Modified', 'action.actions': 'Actions', 'action.item_actions': 'Actions for {0}' },
  zh: { 'sort.name': '名称', 'sort.size': '大小', 'info.modified': '修改时间', 'action.actions': '操作', 'action.item_actions': '{0} 的操作' },
  ja: { 'sort.name': '名前', 'sort.size': 'サイズ', 'info.modified': '更新日', 'action.actions': '操作', 'action.item_actions': '{0} の操作' },
};

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: (string | number)[]) => messages[testLang]?.[key]?.replace('{0}', String(args[0])) ?? key,
  }),
}));

describe('ProjectList translations', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it.each([
    ['en', 'Name', 'Size', 'Modified', 'Actions for demo.txt'],
    ['zh', '名称', '大小', '修改时间', 'demo.txt 的操作'],
    ['ja', '名前', 'サイズ', '更新日', 'demo.txt の操作'],
  ])('renders localized headers and action label in %s', (lang, name, size, modified, actions) => {
    testLang = lang;
    render(
      <ProjectList
        items={[{ name: 'demo.txt', path: 'demo.txt', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.txt', category: 'document' }]}
        selected={new Set()}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByRole('columnheader', { name })).toBeDefined();
    expect(screen.getByRole('columnheader', { name: size })).toBeDefined();
    expect(screen.getByRole('columnheader', { name: modified })).toBeDefined();
    expect(screen.getByRole('button', { name: actions })).toBeDefined();
  });

  it('keeps directory navigation in BrowsePage callbacks and opens on double click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const onNavigate = vi.fn();
    const onZipSelect = vi.fn();
    const onSelect = vi.fn();
    render(
      <ProjectList
        items={[{ name: 'nested', path: 'parent/nested', type: 'dir', extension: '', category: 'other' }]}
        selected={new Set()}
        onSelect={onSelect}
        onZipSelect={onZipSelect}
        onInspect={onInspect}
        onDoubleClick={onDoubleClick}
        onNavigate={onNavigate}
      />,
    );

    const directory = screen.getByRole('button', { name: 'nested' });
    fireEvent.click(directory);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledTimes(1);
    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({ path: 'parent/nested' }));
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.doubleClick(directory);
    fireEvent.keyDown(directory, { key: 'Enter' });

    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({ path: 'parent/nested' }));
    expect(onSelect).not.toHaveBeenCalled();
    expect(onDoubleClick).toHaveBeenCalledTimes(2);
    expect(onDoubleClick).toHaveBeenCalledWith(expect.objectContaining({ path: 'parent/nested' }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(onZipSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Select nested for ZIP download' })).toBeNull();
  });

  it('keeps the ZIP selection control for files', () => {
    const onZipSelect = vi.fn();
    render(
      <ProjectList
        items={[{ name: 'asset.png', path: 'asset.png', type: 'file', extension: '.png', category: 'image' }]}
        selected={new Set()}
        onSelect={vi.fn()}
        onZipSelect={onZipSelect}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Select asset.png for ZIP download' }));
    expect(onZipSelect).toHaveBeenCalledWith('asset.png');
  });

  it('preserves project metadata in inspect and open payloads', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const onSelect = vi.fn();
    const project = { name: 'Project', path: 'Project', type: 'dir' as const, extension: '', category: 'other', is_project: true };
    render(<ProjectList items={[project]} selected={new Set()} onSelect={onSelect} onInspect={onInspect} onDoubleClick={onDoubleClick} />);

    const button = screen.getByRole('button', { name: 'Project' });
    fireEvent.click(button);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    fireEvent.doubleClick(button);

    expect(onInspect).toHaveBeenCalledWith(project);
    expect(onSelect).not.toHaveBeenCalled();
    expect(onDoubleClick).toHaveBeenCalledWith(project);
  });

  it('inspects the complete item on a normal desktop click', () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    const project = { name: 'Project', path: 'Project', type: 'dir' as const, extension: '', category: 'other', is_project: true };
    render(<ProjectList items={[project]} selected={new Set()} onSelect={onSelect} onInspect={onInspect} />);

    fireEvent.click(screen.getByRole('button', { name: 'Project' }));
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);

    expect(onInspect).toHaveBeenCalledWith(project);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('cancels a pending inspect when Enter opens the item', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectList items={[item]} selected={new Set()} onSelect={vi.fn()} onInspect={onInspect} onDoubleClick={onDoubleClick} />);

    const asset = screen.getByRole('button', { name: 'asset.png' });
    fireEvent.click(asset);
    fireEvent.keyDown(asset, { key: 'Enter' });
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);

    expect(onDoubleClick).toHaveBeenCalledTimes(1);
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('does not inspect before a delayed browser double click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const project = { name: 'Project', path: 'Project', type: 'dir' as const, extension: '', category: 'other' };
    render(<ProjectList items={[project]} selected={new Set()} onSelect={vi.fn()} onInspect={onInspect} onDoubleClick={onDoubleClick} />);

    const button = screen.getByRole('button', { name: 'Project' });
    fireEvent.click(button);
    vi.advanceTimersByTime(250);
    fireEvent.doubleClick(button);

    expect(onInspect).not.toHaveBeenCalled();
    expect(onDoubleClick).toHaveBeenCalledTimes(1);
  });

  it('toggles selection in selection mode without inspecting', () => {
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectList items={[item]} selected={new Set()} onSelect={onSelect} onInspect={onInspect} selectionMode />);

    fireEvent.click(screen.getByRole('button', { name: 'asset.png' }));

    expect(onSelect).toHaveBeenCalledWith('asset.png');
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('selects the path on Enter in selection mode instead of opening', () => {
    const onSelect = vi.fn();
    const onDoubleClick = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectList items={[item]} selected={new Set()} onSelect={onSelect} onInspect={vi.fn()} onDoubleClick={onDoubleClick} selectionMode />);

    fireEvent.keyDown(screen.getByRole('button', { name: 'asset.png' }), { key: 'Enter' });

    expect(onSelect).toHaveBeenCalledWith('asset.png');
    expect(onDoubleClick).not.toHaveBeenCalled();
  });

  it('navigates a directory on mobile single click', () => {
    const onNavigate = vi.fn();
    const onInspect = vi.fn();
    render(<ProjectList items={[{ name: 'Assets', path: 'Assets', type: 'dir', extension: '', category: 'other' }]} selected={new Set()} onSelect={vi.fn()} onInspect={onInspect} onNavigate={onNavigate} isMobile />);

    fireEvent.click(screen.getByRole('button', { name: 'Assets' }));

    expect(onNavigate).toHaveBeenCalledWith('Assets');
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('selects a directory before mobile navigation in selection mode', () => {
    const onSelect = vi.fn();
    const onNavigate = vi.fn();
    render(<ProjectList items={[{ name: 'Assets', path: 'Assets', type: 'dir', extension: '', category: 'other' }]} selected={new Set()} onSelect={onSelect} onNavigate={onNavigate} isMobile selectionMode />);

    fireEvent.click(screen.getByRole('button', { name: 'Assets' }));

    expect(onSelect).toHaveBeenCalledWith('Assets');
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('inspects a file immediately on mobile single click', () => {
    vi.useFakeTimers();
    const onInspect = vi.fn();
    const item = { name: 'asset.png', path: 'asset.png', type: 'file' as const, extension: '.png', category: 'image' };
    render(<ProjectList items={[item]} selected={new Set()} onSelect={vi.fn()} onInspect={onInspect} isMobile />);

    fireEvent.click(screen.getByRole('button', { name: 'asset.png' }));

    expect(onInspect).toHaveBeenCalledWith(item);
    vi.advanceTimersByTime(SINGLE_CLICK_DELAY_MS);
    expect(onInspect).toHaveBeenCalledTimes(1);
  });

  it('renders directory thumbnails in the icon cell', () => {
    render(
      <ProjectList
        items={[{ name: 'nested', path: 'parent/nested', type: 'dir', extension: '', category: 'other' }]}
        selected={new Set()}
        onSelect={() => {}}
        thumbnailMap={{ 'parent/nested': '/api/thumbnails/nested/cover.png' }}
      />,
    );

    expect(screen.getByRole('img').getAttribute('src')).toBe('/api/thumbnails/nested/cover.png');
  });
});
