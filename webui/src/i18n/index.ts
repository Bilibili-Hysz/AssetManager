import en from './en';
import zh from './zh';
import ja from './ja';
import type { I18nDict } from './en';

const dictionaries: Record<string, I18nDict> = { en, zh, ja };

const SUPPORTED_LANGS = ['en', 'zh', 'ja'] as const;
type Lang = (typeof SUPPORTED_LANGS)[number];

function detectLang(): Lang {
  try {
    const stored = localStorage.getItem('am_lang');
    if (stored && SUPPORTED_LANGS.includes(stored as Lang)) return stored as Lang;
  } catch { /* localStorage not available */ }
  const browserLang = navigator.language.slice(0, 2);
  if (SUPPORTED_LANGS.includes(browserLang as Lang)) return browserLang as Lang;
  return 'en';
}

let currentLang: Lang = detectLang();
let currentDict: I18nDict = dictionaries[currentLang] ?? en;
const listeners = new Set<() => void>();

export function t(key: string, ...args: (string | number)[]): string {
  const keys = key.split('.');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = currentDict;
  for (const k of keys) {
    value = value?.[k];
    if (value === undefined) return key;
  }
  if (typeof value === 'string') {
    let result: string = value;
    args.forEach((arg, i) => { result = result.replace(`{${i}}`, String(arg)); });
    return result;
  }
  return key;
}

export function setLang(lang: Lang): void {
  currentLang = lang;
  currentDict = dictionaries[lang] ?? en;
  try { localStorage.setItem('am_lang', lang); } catch { /* ignore */ }
  listeners.forEach(listener => listener());
}

export function getLang(): Lang {
  return currentLang;
}

export function subscribeToLang(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export type { Lang };
export { SUPPORTED_LANGS };
