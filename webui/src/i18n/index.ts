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
    // split/join replaces every occurrence (String.prototype.replaceAll needs
    // ES2021; the project targets ES2020).
    args.forEach((arg, i) => { result = result.split(`{${i}}`).join(String(arg)); });
    return result;
  }
  return key;
}

/** Keep the <html lang> attribute and document title in sync with the active locale. */
function applyLangToDocument(): void {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = currentLang;
  // app.title exists in every dictionary (en/zh/ja); t() falls back to the key
  // itself if it is ever missing.
  document.title = t('app.title');
}

export function setLang(lang: Lang): void {
  currentLang = lang;
  currentDict = dictionaries[lang] ?? en;
  try { localStorage.setItem('am_lang', lang); } catch { /* ignore */ }
  applyLangToDocument();
  listeners.forEach(listener => listener());
}

// Apply the initially detected language immediately (stored preference or
// browser language) so <html lang> and the title match before first paint.
applyLangToDocument();

export function getLang(): Lang {
  return currentLang;
}

export function subscribeToLang(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export type { Lang };
export { SUPPORTED_LANGS };
