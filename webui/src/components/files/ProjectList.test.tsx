// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
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
});
