// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectList } from './ProjectList';

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
  afterEach(cleanup);

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

  it('navigates directories without inspecting, opening details, or selecting ZIP items', () => {
    const onNavigate = vi.fn();
    const onInspect = vi.fn();
    const onDoubleClick = vi.fn();
    const onZipSelect = vi.fn();
    render(
      <ProjectList
        items={[{ name: 'nested', path: 'parent/nested', type: 'dir', extension: '', category: 'other' }]}
        selected={new Set()}
        onSelect={vi.fn()}
        onZipSelect={onZipSelect}
        onInspect={onInspect}
        onDoubleClick={onDoubleClick}
        onNavigate={onNavigate}
      />,
    );

    const directory = screen.getByRole('button', { name: 'nested' });
    fireEvent.click(directory);
    fireEvent.doubleClick(directory);
    fireEvent.keyDown(directory, { key: 'Enter' });

    expect(onNavigate).toHaveBeenCalledTimes(3);
    expect(onNavigate).toHaveBeenCalledWith('parent/nested');
    expect(onInspect).not.toHaveBeenCalled();
    expect(onDoubleClick).not.toHaveBeenCalled();
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
});
