import { describe, expect, it } from 'vitest';
import en from '../i18n/en';
import ja from '../i18n/ja';
import zh from '../i18n/zh';
import { SHORTCUTS, SHORTCUT_SCOPES, shortcutsByScope } from './registry';

const dictionaries = { en, zh, ja } as const;

function resolve(dict: Record<string, unknown>, key: string): unknown {
  return key.split('.').reduce<unknown>((acc, part) =>
    (acc as Record<string, unknown> | undefined)?.[part], dict);
}

describe('shortcuts registry integrity', () => {
  it('every entry has non-empty display keys and a known scope', () => {
    expect(SHORTCUTS.length).toBeGreaterThan(0);
    for (const entry of SHORTCUTS) {
      expect(entry.keys.length, `${entry.descriptionKey} needs keys`).toBeGreaterThan(0);
      for (const key of entry.keys) {
        expect(key.trim().length, `${entry.descriptionKey} key label`).toBeGreaterThan(0);
      }
      expect(SHORTCUT_SCOPES, `${entry.descriptionKey} scope`).toContain(entry.scope);
    }
  });

  it('every descriptionKey resolves to a non-empty string in all three locales', () => {
    for (const entry of SHORTCUTS) {
      for (const [locale, dict] of Object.entries(dictionaries)) {
        const value = resolve(dict as Record<string, unknown>, entry.descriptionKey);
        expect(typeof value, `${locale}.${entry.descriptionKey} must exist`).toBe('string');
        expect((value as string).trim().length, `${locale}.${entry.descriptionKey}`).toBeGreaterThan(0);
      }
    }
  });

  it('has at least one entry per scope so no group header renders empty', () => {
    for (const scope of SHORTCUT_SCOPES) {
      expect(shortcutsByScope(scope).length, `scope ${scope}`).toBeGreaterThan(0);
    }
  });

  it('keeps entries unique by descriptionKey (one row per shortcut)', () => {
    const keys = SHORTCUTS.map(entry => entry.descriptionKey);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
