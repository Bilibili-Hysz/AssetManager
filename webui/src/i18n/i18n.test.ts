// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import en from './en';
import ja from './ja';
import zh from './zh';
import { getLang, setLang, subscribeToLang, t } from './index';

function flatten(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return typeof v === 'string' ? [key] : flatten(v as Record<string, unknown>, key);
  });
}

function placeholders(value: string): string[] {
  return Array.from(value.matchAll(/\{\d+\}/g), m => m[0]);
}

function checkKeys(translation: Record<string, unknown>, locale: string) {
  const targetKeys = flatten(translation);
  const enKeySet = new Set(flatten(en));
  const targetKeySet = new Set(targetKeys);
  const missing = targetKeys.filter(k => !enKeySet.has(k));
  const extra = flatten(en).filter(k => !targetKeySet.has(k));
  expect([...missing], `${locale} is missing keys`).toEqual([]);
  expect([...extra], `${locale} has unknown keys`).toEqual([]);
}

describe('i18n parity', () => {
  it('zh has exactly the same key structure as en', () => {
    checkKeys(zh, 'zh');
  });

  it('ja has exactly the same key structure as en', () => {
    checkKeys(ja, 'ja');
  });

  it('every value is a non-empty string in every locale', () => {
    for (const [locale, dict] of Object.entries({ en, zh, ja })) {
      for (const key of flatten(dict)) {
        const value = key.split('.').reduce<unknown>((acc: unknown, k: string) =>
          (acc as Record<string, unknown>)?.[k], dict);
        expect(typeof value, `${locale}.${key} should be a string`).toBe('string');
        expect((value as string).trim().length, `${locale}.${key} should not be empty`).toBeGreaterThan(0);
      }
    }
  });

  it('keeps the same {n} placeholders across locales', () => {
    for (const key of flatten(en)) {
      const enValue = key.split('.').reduce<unknown>((acc: unknown, k: string) =>
        (acc as Record<string, unknown>)?.[k], en) as string;
      const enPlaceholders = placeholders(enValue).sort();
      for (const [locale, dict] of Object.entries({ zh, ja })) {
        const value = key.split('.').reduce<unknown>((acc: unknown, k: string) =>
          (acc as Record<string, unknown>)?.[k], dict) as string;
        expect(placeholders(value).sort(), `${locale}.${key} placeholder mismatch`).toEqual(enPlaceholders);
      }
    }
  });

  it('selects a stored language via setLang and notifies subscribers', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToLang(listener);

    setLang('zh');
    expect(getLang()).toBe('zh');
    expect(t('app.title')).toBe(zh.app.title);
    expect(listener).toHaveBeenCalledOnce();

    unsubscribe();
    setLang('ja');
    expect(listener).toHaveBeenCalledOnce();
    expect(t('app.title')).toBe(ja.app.title);
  });
});
